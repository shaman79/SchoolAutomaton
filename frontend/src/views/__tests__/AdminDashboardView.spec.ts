/**
 * Admin console: Overview / Settings / Audit tabs, the open tab kept in the URL (?tab=), and an
 * expired session sending the admin back to the login (token cleared, return path kept).
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { adminDashboard: vi.fn(), adminConfig: vi.fn(), adminAudit: vi.fn() },
  }
})

import type { AdminConfigOut, DashboardOut } from '@/components/admin/adminApi'
import { i18n, setLocale } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import { ADMIN_TOKEN_KEY } from '@/router'
import AdminDashboardView from '@/views/admin/AdminDashboardView.vue'

import { clearToasts, stubDom, toastTexts } from './fixtures'

const mocked = api as unknown as Record<string, Mock>

const DASHBOARD: DashboardOut = {
  requests_24h: 42,
  decisions_breakdown: { proceed: 40, refuse: 2 },
  anthropic_cost_usd: 1.25,
  replicate_cost_usd: 0.1,
  cache_hit_rate: 0.5,
  crisis_events: 0,
  refusals: 2,
  injection_attempts: 0,
  profiles_total: 7,
  lessons_total: 12,
  quizzes_total: 5,
}
const CONFIG: AdminConfigOut = {
  can_edit: true,
  items: [],
  usage_today: [],
  spent_today_usd: 0,
  budget_usd: 100,
  day_started_at: '2026-10-29T00:00:00Z',
}

function makeAdminRouter() {
  const blank = { template: '<div />' }
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/admin', name: 'admin', component: AdminDashboardView },
      { path: '/admin/login', name: 'admin-login', component: blank },
    ],
  })
}

async function open(path: string) {
  const router = makeAdminRouter()
  await router.push(path)
  await router.isReady()
  const w = mount({ template: '<RouterView />' }, { global: { plugins: [i18n, router] } })
  await flushPromises()
  return { w, router }
}

beforeEach(() => {
  stubDom()
  vi.clearAllMocks()
  clearToasts()
  localStorage.setItem(ADMIN_TOKEN_KEY, 'jwt-token')
  mocked.adminDashboard.mockResolvedValue(DASHBOARD)
  mocked.adminConfig.mockResolvedValue(CONFIG)
  mocked.adminAudit.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
})
afterEach(() => {
  clearToasts()
  localStorage.clear()
  setLocale('en')
})

it('opens on the Overview with the dashboard numbers', async () => {
  const { w } = await open('/admin')
  expect(w.find('h1').text()).toBe('Admin console')
  expect(mocked.adminDashboard).toHaveBeenCalledWith('jwt-token')
  const tabs = w.findAll('[role="tab"]')
  expect(tabs.map((t) => t.text())).toEqual(['Overview', 'Settings', 'Audit'])
  expect(tabs[0].attributes('aria-selected')).toBe('true')
  expect(w.find('[role="tabpanel"]').attributes('aria-labelledby')).toBe('admin-tab-overview')
  expect(w.text()).toContain('Last 24 hours')
  expect(w.text()).toContain('42')
})

it('switches tabs and keeps the open tab in the URL', async () => {
  const { w, router } = await open('/admin')
  await w.find('[data-test="tab-settings"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query.tab).toBe('settings')
  expect(w.find('[data-test="tab-settings"]').attributes('aria-selected')).toBe('true')
  expect(mocked.adminConfig).toHaveBeenCalledWith('jwt-token')
  expect(w.text()).toContain(i18n.global.t('admin.settings.sections.spending'))

  await w.find('[data-test="tab-audit"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query.tab).toBe('audit')
  expect(mocked.adminAudit).toHaveBeenCalled()

  await w.find('[data-test="tab-overview"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query.tab).toBeUndefined()
  expect(w.text()).toContain('Last 24 hours')
})

it('honours ?tab= on arrival (and does not load the overview it is not showing)', async () => {
  const { w } = await open('/admin?tab=settings')
  expect(w.find('[data-test="tab-settings"]').attributes('aria-selected')).toBe('true')
  expect(w.find('[data-test="tab-overview"]').attributes('tabindex')).toBe('-1')
  expect(mocked.adminConfig).toHaveBeenCalledTimes(1)
  expect(mocked.adminDashboard).not.toHaveBeenCalled()
})

it('an unknown ?tab= falls back to the Overview', async () => {
  const { w } = await open('/admin?tab=content')
  expect(w.find('[data-test="tab-overview"]').attributes('aria-selected')).toBe('true')
  expect(w.find('[data-test="tab-content"]').exists()).toBe(false)
})

it('arrow keys move between tabs', async () => {
  const { w, router } = await open('/admin')
  await w.find('[data-test="tab-overview"]').trigger('keydown', { key: 'ArrowRight' })
  await flushPromises()
  expect(router.currentRoute.value.query.tab).toBe('settings')
  await w.find('[data-test="tab-settings"]').trigger('keydown', { key: 'End' })
  await flushPromises()
  expect(router.currentRoute.value.query.tab).toBe('audit')
  await w.find('[data-test="tab-audit"]').trigger('keydown', { key: 'ArrowRight' })
  await flushPromises()
  expect(router.currentRoute.value.query.tab).toBeUndefined() // wrapped round to the Overview
})

it('a 401 on the dashboard clears the token and goes to the login, keeping the way back', async () => {
  mocked.adminDashboard.mockRejectedValue(new ApiError(401, 'Invalid or expired token'))
  const { router } = await open('/admin')
  expect(localStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull()
  expect(router.currentRoute.value.name).toBe('admin-login')
  expect(router.currentRoute.value.query.redirect).toBe('/admin')
  expect(toastTexts()).toEqual([i18n.global.t('admin.session_expired')])
})

it('an expired session on the Settings tab does the same', async () => {
  mocked.adminConfig.mockRejectedValue(new ApiError(401, 'Invalid or expired token'))
  const { router } = await open('/admin?tab=settings')
  expect(localStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull()
  expect(router.currentRoute.value.name).toBe('admin-login')
  expect(router.currentRoute.value.query.redirect).toBe('/admin?tab=settings')
})

it('other dashboard failures offer a retry', async () => {
  mocked.adminDashboard.mockRejectedValueOnce(new ApiError(500, 'Internal Server Error'))
  const { w } = await open('/admin')
  const alert = w.find('[role="alert"]')
  expect(alert.text()).toContain(i18n.global.t('admin.load_error'))
  await alert.find('button').trigger('click')
  await flushPromises()
  expect(w.text()).toContain('Last 24 hours')
})

it('Sign out clears the token', async () => {
  const { w, router } = await open('/admin')
  await w.find('header button').trigger('click')
  await flushPromises()
  expect(localStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull()
  expect(router.currentRoute.value.name).toBe('admin-login')
})

it('is localized in Czech', async () => {
  setLocale('cs')
  const { w } = await open('/admin')
  expect(w.find('h1').text()).toBe('Administrátorská konzole')
  expect(w.findAll('[role="tab"]').map((t) => t.text())).toEqual(['Přehled', 'Nastavení', 'Audit'])
  expect(w.find('[role="tablist"]').attributes('aria-label')).toBe('Části administrace')
})

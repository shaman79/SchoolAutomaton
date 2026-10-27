/**
 * /resume?code=…: a device that already learns with a DIFFERENT code shows that code (to write down)
 * and asks before switching; a device without a code resumes at once; the same code is a no-op.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { beforeEach, expect, it, vi, type Mock } from 'vitest'

const stored = vi.hoisted(() => ({ code: null as string | null }))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { resumeProfile: vi.fn(), getMe: vi.fn() },
    getResumeCode: () => stored.code,
    setResumeCode: vi.fn((c: string | null) => {
      stored.code = c
    }),
  }
})

import { i18n } from '@/i18n'
import { ApiError, NETWORK_ERROR_STATUS, api } from '@/lib/api'
import { useSessionStore } from '@/stores/session'
import ResumeView from '@/views/ResumeView.vue'

import { makeRouter, stubDom } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
let pinia: Pinia

const envelope = {
  profile: { id: 7, display_name: null, total_xp: 0, level: 1, age_band: 'unknown', primary_language: 'cs', created_at: null },
  settings: { locale: 'cs', education_locale: 'cs-CZ', school_year: null },
  gamification: { level: 1, total_xp: 0 },
}

async function openResume(query = '') {
  const router = makeRouter()
  router.addRoute({ path: '/resume', name: 'resume', component: ResumeView })
  await router.push(`/resume${query}`)
  await router.isReady()
  const w = mount({ template: '<RouterView />' }, { global: { plugins: [pinia, i18n, router] } })
  await flushPromises()
  return { w, router }
}
const button = (w: ReturnType<typeof mount>, key: string) =>
  w.findAll('button').find((b) => b.text().includes(i18n.global.t(key)))

beforeEach(() => {
  stubDom()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  mocked.resumeProfile.mockResolvedValue(envelope)
})

it('asks before replacing this device’s code, showing it so it can be written down', async () => {
  stored.code = 'OLD1-CODE'
  const { w, router } = await openResume('?code=NEW2-CODE')

  expect(mocked.resumeProfile).not.toHaveBeenCalled()
  expect(w.text()).toContain(i18n.global.t('resume.switch_title'))
  expect(w.text()).toContain('OLD1-CODE')
  expect(w.text()).toContain('NEW2-CODE')
  expect(router.currentRoute.value.query.code).toBeUndefined() // taken out of the address bar

  await button(w, 'resume.switch_confirm')!.trigger('click')
  await flushPromises()
  expect(mocked.resumeProfile).toHaveBeenCalledWith('NEW2-CODE')
  expect(useSessionStore().resumeCode).toBe('NEW2-CODE')
  expect(router.currentRoute.value.name).toBe('home')
})

it('"keep my code" leaves everything as it was', async () => {
  stored.code = 'OLD1-CODE'
  const { w, router } = await openResume('?code=NEW2-CODE')
  await button(w, 'resume.switch_keep')!.trigger('click')
  await flushPromises()
  expect(mocked.resumeProfile).not.toHaveBeenCalled()
  expect(useSessionStore().resumeCode).toBe('OLD1-CODE')
  expect(router.currentRoute.value.name).toBe('home')
})

it('a device without a code resumes straight away', async () => {
  stored.code = null
  const { router } = await openResume('?code=new2-code')
  expect(mocked.resumeProfile).toHaveBeenCalledWith('NEW2-CODE')
  expect(useSessionStore().resumeCode).toBe('NEW2-CODE')
  expect(router.currentRoute.value.name).toBe('home')
})

it('the same code (any spelling) changes nothing', async () => {
  stored.code = 'OLD1-CODE'
  const { router } = await openResume('?code=old1code')
  expect(mocked.resumeProfile).not.toHaveBeenCalled()
  expect(router.currentRoute.value.name).toBe('home')
})

it('an offline failure says so kindly instead of "code not found"', async () => {
  stored.code = null
  mocked.resumeProfile.mockRejectedValue(new ApiError(NETWORK_ERROR_STATUS, 'net'))
  const { w } = await openResume('?code=NEW2-CODE')
  expect(w.find('[role="alert"]').text()).toBe(i18n.global.t('errors.network'))
  mocked.resumeProfile.mockRejectedValue(new ApiError(404, 'Unknown resume code'))
  await w.find('form').trigger('submit')
  await flushPromises()
  expect(w.find('[role="alert"]').text()).toBe(i18n.global.t('resume.not_found'))
})

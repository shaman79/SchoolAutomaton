/**
 * Home: a failed prompt never shows raw/technical text ("[object Object]", English server detail),
 * and a learner whose profile can't be reached keeps their code (no new profile).
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { beforeEach, expect, it, vi, type Mock } from 'vitest'

const stored = vi.hoisted(() => ({ code: null as string | null }))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      getMe: vi.fn(),
      createProfile: vi.fn(),
      getGamification: vi.fn(),
      submitPrompt: vi.fn(),
      getContinue: vi.fn(),
      getRecommendations: vi.fn(),
      getMyAssignments: vi.fn(),
    },
    getResumeCode: () => stored.code,
    setResumeCode: vi.fn((c: string | null) => {
      stored.code = c
    }),
  }
})

import ConnectionBanner from '@/components/common/ConnectionBanner.vue'
import { i18n } from '@/i18n'
import { ApiError, NETWORK_ERROR_STATUS, api } from '@/lib/api'
import { useSessionStore } from '@/stores/session'
import HomeView from '@/views/HomeView.vue'

import { makeRouter, stubDom } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
let pinia: Pinia

function mountHome() {
  return mount(HomeView, {
    global: {
      plugins: [pinia, i18n, makeRouter()],
      stubs: { DailyReviewCard: true, ResumeCodeCard: true, SuggestionsStrip: true },
    },
  })
}
async function submit(w: ReturnType<typeof mountHome>, text = 'Teach me fractions') {
  await w.find('textarea').setValue(text)
  await w.find('form').trigger('submit')
  await vi.runAllTimersAsync()
  await flushPromises()
}

beforeEach(() => {
  stubDom()
  vi.useFakeTimers()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  stored.code = 'OLD1-CODE'
  mocked.getContinue.mockResolvedValue(null)
  mocked.getRecommendations.mockResolvedValue([])
  mocked.getMyAssignments.mockResolvedValue([])
  mocked.getMe.mockResolvedValue({
    profile: { id: 1, display_name: null, total_xp: 50, level: 1, age_band: 'unknown', primary_language: 'cs', created_at: null },
    settings: { locale: 'en', education_locale: 'en-US', school_year: null },
    gamification: { level: 1, total_xp: 50 },
  })
})

it('a validation error is shown as friendly words, not "[object Object]"', async () => {
  mocked.submitPrompt.mockRejectedValue(new ApiError(422, 'Unprocessable', undefined, [{ msg: 'x' }]))
  const w = mountHome()
  await submit(w)
  const err = w.find('#prompt-error')
  expect(err.text()).toBe(i18n.global.t('errors.too_long'))
  expect(err.text()).not.toContain('[object Object]')
})

it('a rate limit says "slow down", not the server’s English detail', async () => {
  mocked.submitPrompt.mockRejectedValue(
    new ApiError(429, "You're going a bit fast. Please wait a moment and try again.", undefined, 'x', 30),
  )
  const w = mountHome()
  await submit(w)
  expect(w.find('#prompt-error').text()).toBe(i18n.global.t('errors.slow_down'))
})

it('an unreachable server keeps the code, creates no profile, and shows one "can’t reach" message with Retry', async () => {
  mocked.getMe.mockRejectedValue(new ApiError(NETWORK_ERROR_STATUS, 'net'))
  const banner = mount(ConnectionBanner, { global: { plugins: [pinia, i18n, makeRouter()] } })
  const w = mountHome()
  await submit(w)

  expect(mocked.createProfile).not.toHaveBeenCalled()
  expect(mocked.submitPrompt).not.toHaveBeenCalled()
  expect(useSessionStore().resumeCode).toBe('OLD1-CODE')
  expect(w.find('#prompt-error').exists()).toBe(false) // the banner says it (no double message)
  expect(banner.text()).toContain(i18n.global.t('errors.connection_title'))

  // Retry once the connection is back: the banner goes away.
  mocked.getMe.mockReset().mockResolvedValue({
    profile: { id: 1, display_name: null, total_xp: 50, level: 1, age_band: 'unknown', primary_language: 'cs', created_at: null },
    settings: { locale: 'en', education_locale: 'en-US', school_year: null },
    gamification: { level: 1, total_xp: 50 },
  })
  await banner.find('button').trigger('click')
  await vi.runAllTimersAsync()
  await flushPromises()
  expect(banner.text()).toBe('')
})

it('what is waiting comes first, in one list, each session once', async () => {
  const progress = { position: 2, total: 5, completed: false, last_active_at: null }
  mocked.getMyAssignments.mockResolvedValue([
    { id: 1, request_id: 'task-1', mode: 'test', title: 'Násobilka 7', subject: 'math', created_at: null,
      status: 'started', progress, result: null },
    { id: 2, request_id: 'task-2', mode: 'study', title: 'Zlomky', subject: 'math', created_at: null,
      status: 'ready', progress: null, result: null },
  ])
  mocked.getContinue.mockResolvedValue({
    request_id: 'task-1', mode: 'test', status: 'ready', lesson_id: null, quiz_id: 3, title: 'Násobilka 7',
    subject: 'math', created_at: null, progress,
  })
  const w = mountHome()
  await vi.runAllTimersAsync()
  await flushPromises()
  const rows = w.find('.sa-wait').findAll('a')
  expect(rows.map((a) => a.attributes('href'))).toEqual(['/test/task-1', '/lesson/task-2'])
  // Above the hero question, which sits right on its input (no second visible label).
  const html = w.html()
  expect(html.indexOf('sa-wait')).toBeLessThan(html.indexOf('sa-home-title'))
  expect(html.indexOf('sa-home-title')).toBeLessThan(html.indexOf('sa-prompt'))
  expect(w.find('label[for="prompt"]').classes()).toContain('sr-only')
})

it('a device that follows children as a parent links to their overview', async () => {
  const { useParentStore } = await import('@/stores/parent')
  useParentStore().children = [
    { id: 'a', code: 'AAAAA-AAAAA', name: 'Anička', addedAt: '' },
    { id: 'b', code: 'BBBBB-BBBBB', name: '', addedAt: '' },
  ]
  const w = mountHome()
  await flushPromises()
  const link = w.find('a.sa-home__parent')
  expect(link.attributes('href')).toBe('/parent')
  expect(link.text()).toContain(i18n.global.t('parent.home_link', { names: 'Anička, ' + i18n.global.t('parent.child_fallback', { n: 2 }) }))
})


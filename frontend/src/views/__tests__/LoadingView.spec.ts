/**
 * LoadingView: a failure to start ends in a friendly reason with Retry (never an endless spinner),
 * and leaving the screen leaves no timer or stream behind.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { startGeneration: vi.fn(), getRequestStatus: vi.fn() },
    streamGeneration: vi.fn(() => ({ close: vi.fn() })),
  }
})

import { i18n } from '@/i18n'
import { ApiError, api, streamGeneration } from '@/lib/api'
import LoadingView from '@/views/LoadingView.vue'

import { makeRouter, stubDom } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
let pinia: Pinia

function mountLoading() {
  return mount(LoadingView, { props: { sessionId: 'R' }, global: { plugins: [pinia, i18n, makeRouter()] } })
}

beforeEach(() => {
  stubDom()
  vi.useFakeTimers()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})
afterEach(() => vi.useRealTimers())

it('a start refused with 429 shows a friendly reason and a working Retry', async () => {
  mocked.startGeneration.mockRejectedValueOnce(new ApiError(429, 'You are going a bit fast', undefined, 'x', 30))
  const w = mountLoading()
  await flushPromises()

  const alert = w.find('[role="alert"]')
  expect(alert.exists()).toBe(true)
  expect(alert.text()).toContain(i18n.global.t('loading.err_slow_down'))
  expect(w.text()).not.toContain('going a bit fast')

  mocked.startGeneration.mockResolvedValueOnce({ request_id: 'R', status: 'queued' })
  const retry = w.findAll('button').find((b) => b.text() === i18n.global.t('common.retry'))
  expect(retry).toBeTruthy()
  await retry!.trigger('click')
  await flushPromises()
  expect(mocked.startGeneration).toHaveBeenCalledTimes(2)
  expect(streamGeneration).toHaveBeenCalledTimes(1)
  expect(w.find('[role="alert"]').exists()).toBe(false)
})

it('today’s budget offers the learner’s lessons instead of a pointless Retry', async () => {
  mocked.startGeneration.mockRejectedValueOnce(new ApiError(503, 'daily_budget', undefined, 'daily_budget'))
  const w = mountLoading()
  await flushPromises()
  expect(w.text()).toContain(i18n.global.t('loading.err_budget'))
  expect(w.text()).not.toContain(i18n.global.t('common.retry'))
  expect(w.text()).toContain(i18n.global.t('loading.my_lessons'))
})

it('leaving the screen stops every timer (cheers, polling)', async () => {
  mocked.startGeneration.mockResolvedValue({ request_id: 'R', status: 'queued' })
  const w = mountLoading()
  await flushPromises()
  expect(vi.getTimerCount()).toBeGreaterThan(0) // cheer rotation + the status safety poll
  w.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

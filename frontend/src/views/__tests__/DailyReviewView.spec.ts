/**
 * Daily review: a card the server won't take any more (404/409) is skipped silently; a support
 * (crisis-net) result shows help instead of a verdict and is not counted.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { getDue: vi.fn(), reviewItem: vi.fn(), getGamification: vi.fn() },
    getResumeCode: () => 'ABCD-EFGH',
  }
})

import { i18n } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import DailyReviewView from '@/views/DailyReviewView.vue'

import { SUPPORT, clearToasts, grade, makeRouter, shortItem, stubDom, supportResult, toastTexts } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
let pinia: Pinia

async function mountDaily() {
  const w = mount(DailyReviewView, {
    global: { plugins: [pinia, i18n, makeRouter()], stubs: { ReadAloudButton: true, QuestionRenderer: true } },
  })
  await flushPromises()
  return w
}
const answerFor = (id: number) => ({ questionId: id, value: 'x', latencyMs: 300, usedHint: false })

beforeEach(() => {
  stubDom()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  clearToasts()
  mocked.getDue.mockResolvedValue({ items: [shortItem(1), shortItem(2)], composition: {} })
  mocked.getGamification.mockResolvedValue({})
})
afterEach(() => clearToasts())

it('a card that is no longer due (409) is skipped silently and the next one appears', async () => {
  mocked.reviewItem.mockRejectedValueOnce(new ApiError(409, 'Item is not due'))
  const w = await mountDaily()
  w.findComponent({ name: 'QuestionRenderer' }).vm.$emit('answer', answerFor(1))
  await flushPromises()
  expect(toastTexts()).toEqual([])
  expect(w.findComponent({ name: 'QuestionRenderer' }).props('item').id).toBe(2)
})

it('when the last card is gone (404) the round simply ends', async () => {
  mocked.getDue.mockResolvedValue({ items: [shortItem(1)], composition: {} })
  mocked.reviewItem.mockRejectedValueOnce(new ApiError(404, 'Unknown item'))
  const w = await mountDaily()
  w.findComponent({ name: 'QuestionRenderer' }).vm.$emit('answer', answerFor(1))
  await flushPromises()
  expect(toastTexts()).toEqual([])
  expect(w.findComponent({ name: 'QuestionRenderer' }).exists()).toBe(false)
  expect(w.text()).toContain(i18n.global.t('daily.empty_title'))
})

it('a support result shows help, is not counted, and the card stays answerable', async () => {
  mocked.reviewItem.mockResolvedValueOnce(supportResult())
  const w = await mountDaily()
  const q = w.findComponent({ name: 'QuestionRenderer' })
  q.vm.$emit('answer', answerFor(1))
  await flushPromises()
  expect(w.text()).toContain(SUPPORT.message)
  expect(q.props('feedback')).toBeNull()
  expect(q.props('disabled')).toBe(false)

  mocked.reviewItem.mockResolvedValueOnce(grade(true))
  q.vm.$emit('answer', answerFor(1))
  await flushPromises()
  expect(q.props('feedback')?.is_correct).toBe(true)
})

it('other failures keep the card answerable with a friendly message', async () => {
  mocked.reviewItem.mockRejectedValueOnce(new ApiError(429, 'Slow', undefined, 'Slow', 5))
  const w = await mountDaily()
  const q = w.findComponent({ name: 'QuestionRenderer' })
  q.vm.$emit('answer', answerFor(1))
  await flushPromises()
  expect(toastTexts()).toEqual([i18n.global.t('test.answer_slow_down')])
  expect(q.props('disabled')).toBe(false)
  expect(q.props('item').id).toBe(1)
})

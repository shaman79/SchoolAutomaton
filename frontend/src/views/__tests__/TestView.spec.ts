/**
 * TestView: the route decides which quiz opens (no flash of the previous one); a support
 * (crisis-net) result shows help instead of a verdict and is not counted; failures are friendly.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      getRequestStatus: vi.fn(),
      getQuiz: vi.fn(),
      startAttempt: vi.fn(),
      saveAttemptPosition: vi.fn(),
      submitAnswer: vi.fn(),
      getGamification: vi.fn(),
    },
  }
})

import { i18n } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import { useGenerationStore } from '@/stores/generation'
import { useTestStore } from '@/stores/test'
import TestView from '@/views/TestView.vue'

import { SUPPORT, clearToasts, makeRouter, quiz, stubDom, supportResult, toastTexts } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
let pinia: Pinia

function mountTest(sessionId: string) {
  return mount(TestView, {
    props: { sessionId },
    global: { plugins: [pinia, i18n, makeRouter()], stubs: { ReadAloudButton: true, QuestionRenderer: true } },
  })
}

beforeEach(() => {
  stubDom()
  sessionStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  clearToasts()
  mocked.getRequestStatus.mockImplementation(async (id: string) => ({
    request_id: id,
    status: 'ready',
    mode: 'test',
    lesson_id: null,
    quiz_id: id === 'B' ? 2 : 1,
  }))
  mocked.getQuiz.mockImplementation(async (id: number) => quiz(id, id === 2 ? 'B' : 'A', `Quiz ${id}`))
  mocked.startAttempt.mockResolvedValue({ attempt_id: 9, started_at: '', resumed: false, current_index: 0, answers: [] })
  mocked.saveAttemptPosition.mockResolvedValue({ current_index: 1 })
})
afterEach(() => clearToasts())

describe('which quiz opens', () => {
  it('opens the route’s quiz, not the one generated last in this tab', async () => {
    const gen = useGenerationStore()
    gen.requestId = 'A'
    gen.quizId = 1
    const w = mountTest('B')
    await flushPromises()
    expect(mocked.getQuiz).toHaveBeenCalledWith(2)
    expect(mocked.getQuiz).not.toHaveBeenCalledWith(1)
    expect(w.text()).toContain('Quiz 2')
  })

  it('never shows the previous quiz while the new one loads', async () => {
    const test = useTestStore()
    test.quiz = quiz(1, 'A', 'Quiz 1')
    mocked.getRequestStatus.mockReturnValue(new Promise(() => {}))
    const w = mountTest('B')
    await flushPromises()
    expect(w.text()).not.toContain('Quiz 1')
  })
})

describe('answering', () => {
  const answer = { questionId: 11, value: 'text', latencyMs: 500, usedHint: false }

  it('a support result shows the help card, is not counted, and the question stays open', async () => {
    mocked.submitAnswer.mockResolvedValue(supportResult())
    const w = mountTest('A')
    await flushPromises()
    const q = w.findComponent({ name: 'QuestionRenderer' })
    q.vm.$emit('answer', answer)
    await flushPromises()
    expect(w.text()).toContain(SUPPORT.message)
    expect(useTestStore().results[11]).toBeUndefined()
    expect(q.props('feedback')).toBeNull()
    expect(q.props('disabled')).toBe(false)
    // Still on the Check step (no "Next" until it is really answered).
    expect(w.text()).toContain(i18n.global.t('common.check'))
  })

  it('a rate-limited answer says "slow down" and stays answerable', async () => {
    mocked.submitAnswer.mockRejectedValue(new ApiError(429, 'Too many', undefined, 'Too many', 5))
    const w = mountTest('A')
    await flushPromises()
    const q = w.findComponent({ name: 'QuestionRenderer' })
    q.vm.$emit('answer', answer)
    await flushPromises()
    expect(toastTexts()).toContain(i18n.global.t('test.answer_slow_down'))
    expect(q.props('disabled')).toBe(false)
  })
})

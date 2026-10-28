/**
 * LessonView: the route decides which lesson opens; a failed answer leaves the question answerable
 * with a friendly message; a support (crisis-net) result shows help instead of a verdict; nothing
 * lingers after the reader is left.
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
      getLesson: vi.fn(),
      syncLessonProgress: vi.fn(),
      generateSection: vi.fn(),
      getSection: vi.fn(),
      getRecommendations: vi.fn(),
      submitAnswer: vi.fn(),
      getGamification: vi.fn(),
    },
  }
})

import { i18n } from '@/i18n'
import { ApiError, NETWORK_ERROR_STATUS, api } from '@/lib/api'
import { useGenerationStore } from '@/stores/generation'
import { useLessonStore } from '@/stores/lesson'
import LessonView from '@/views/LessonView.vue'

import { SUPPORT, clearToasts, grade, lesson, makeRouter, stubDom, supportResult, toastTexts } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
let pinia: Pinia

function mountLesson(sessionId: string) {
  return mount(LessonView, {
    props: { sessionId },
    global: {
      plugins: [pinia, i18n, makeRouter()],
      stubs: { SuggestionsStrip: true, ReadAloudButton: true, LessonAsset: true, QuestionRenderer: true },
    },
  })
}

beforeEach(() => {
  stubDom()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  clearToasts()
  mocked.getRequestStatus.mockImplementation(async (id: string) => ({
    request_id: id,
    status: 'ready',
    mode: 'study',
    lesson_id: id === 'B' ? 2 : 1,
    quiz_id: null,
  }))
  mocked.getLesson.mockImplementation(async (id: number) => lesson(id, id === 2 ? 'B' : 'A', `Lesson ${id}`))
  mocked.syncLessonProgress.mockResolvedValue(null)
  mocked.getRecommendations.mockResolvedValue([])
})
afterEach(() => clearToasts())

describe('which lesson opens', () => {
  it('opens the route’s lesson, not the one generated last in this tab', async () => {
    const gen = useGenerationStore()
    gen.requestId = 'A'
    gen.lessonId = 1 // left over from generating lesson A
    const w = mountLesson('B')
    await flushPromises()
    expect(mocked.getLesson).toHaveBeenCalledWith(2)
    expect(mocked.getLesson).not.toHaveBeenCalledWith(1)
    expect(w.text()).toContain('Lesson 2')
  })

  it('still uses the generated id when it belongs to this route (no extra request)', async () => {
    const gen = useGenerationStore()
    gen.requestId = 'B'
    gen.lessonId = 2
    mountLesson('B')
    await flushPromises()
    expect(mocked.getRequestStatus).not.toHaveBeenCalled()
    expect(mocked.getLesson).toHaveBeenCalledWith(2)
  })

  it('never flashes the previously opened lesson while the new one loads', async () => {
    useLessonStore().lesson = lesson(1, 'A', 'Lesson 1') // what the reader showed before
    mocked.getRequestStatus.mockReturnValue(new Promise(() => {})) // still resolving B
    const w = mountLesson('B')
    await flushPromises()
    expect(w.text()).not.toContain('Lesson 1')
  })
})

describe('answering', () => {
  async function openWithQuestion() {
    const w = mountLesson('A')
    await flushPromises()
    const q = w.findComponent({ name: 'QuestionRenderer' })
    expect(q.exists()).toBe(true)
    return { w, q }
  }
  const answer = { questionId: 11, value: 'my long answer', latencyMs: 900, usedHint: false }

  it('a failed submit shows a friendly message and leaves the question answerable', async () => {
    mocked.submitAnswer.mockRejectedValue(new ApiError(NETWORK_ERROR_STATUS, 'net'))
    const { q } = await openWithQuestion()
    q.vm.$emit('answer', answer)
    await flushPromises()
    expect(toastTexts().join(' ')).toContain(i18n.global.t('test.answer_network'))
    expect(q.props('disabled')).toBe(false)
    expect(q.props('feedback')).toBeNull()
  })

  it('429 says "slow down", 422 says "too long" — never the server’s words', async () => {
    const { q } = await openWithQuestion()
    mocked.submitAnswer.mockRejectedValueOnce(new ApiError(429, 'Too many answers', undefined, 'Too many answers', 10))
    q.vm.$emit('answer', answer)
    await flushPromises()
    mocked.submitAnswer.mockRejectedValueOnce(new ApiError(422, 'Unprocessable', undefined, [{ msg: 'x' }]))
    q.vm.$emit('answer', answer)
    await flushPromises()
    const texts = toastTexts().join(' ')
    expect(texts).toContain(i18n.global.t('test.answer_slow_down'))
    expect(texts).toContain(i18n.global.t('errors.answer_too_long'))
    expect(texts).not.toMatch(/Too many answers|\[object Object\]/)
    expect(q.props('disabled')).toBe(false)
  })

  it('a support result shows the help card instead of a verdict, and the question stays open', async () => {
    mocked.submitAnswer.mockResolvedValue(supportResult())
    const { w, q } = await openWithQuestion()
    q.vm.$emit('answer', answer)
    await flushPromises()
    expect(w.text()).toContain(SUPPORT.message)
    expect(w.text()).toContain('Linka bezpečí')
    expect(q.props('feedback')).toBeNull() // no "wrong" feedback / sound
    expect(q.props('disabled')).toBe(false)
    expect(useLessonStore().feedbackByItem[11]).toBeUndefined() // not recorded

    mocked.submitAnswer.mockResolvedValue(grade(true))
    q.vm.$emit('answer', answer) // they can still answer it
    await flushPromises()
    expect(useLessonStore().feedbackByItem[11]?.is_correct).toBe(true)
  })

  it('announces a badge the answer unlocked, as the quiz does', async () => {
    mocked.submitAnswer.mockResolvedValue(
      grade(false, { new_badges: [{ code: 'resilient', title: 'Resilient', tier: 1 }] }),
    )
    const { q } = await openWithQuestion()
    q.vm.$emit('answer', answer)
    await flushPromises()
    expect(toastTexts()).toContain(i18n.global.t('test.badge_unlocked', { title: 'Resilient' }))
  })
})

it('leaving while the lesson is still loading leaves no scroll listener behind', async () => {
  let release!: (l: unknown) => void
  mocked.getLesson.mockReturnValue(new Promise((r) => (release = r)))
  const add = vi.spyOn(window, 'addEventListener')
  const w = mountLesson('A')
  await flushPromises()
  w.unmount()
  release(lesson(1, 'A', 'Lesson 1'))
  await flushPromises()
  expect(add.mock.calls.filter(([type]) => type === 'scroll' || type === 'pagehide')).toEqual([])
  add.mockRestore()
})

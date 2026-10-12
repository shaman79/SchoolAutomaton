/**
 * Resume where you left off: on load, the test + lesson stores rebuild the learner's exact state from
 * the server (position + already-graded answers), and keep the server told as the learner moves on.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GradeResult, Lesson, LessonSection, Quiz } from '@/types/session'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      getQuiz: vi.fn(),
      startAttempt: vi.fn(),
      saveAttemptPosition: vi.fn(),
      submitAnswer: vi.fn(),
      getLesson: vi.fn(),
      syncLessonProgress: vi.fn(),
      generateSection: vi.fn(),
      getSection: vi.fn(),
      getGamification: vi.fn(),
    },
  }
})

import { ApiError, api } from '@/lib/api'
import { useLessonStore } from '@/stores/lesson'
import { useTestStore } from '@/stores/test'

const mocked = vi.mocked(api)

function grade(is_correct: boolean): GradeResult {
  return {
    is_correct,
    partial_credit: is_correct ? 1 : 0,
    correct_answer: 'a',
    fsrs_rating: is_correct ? 3 : 1,
    next_due: null,
    explanation: 'Because.',
    misconception: null,
    feedback: { text: 'ok', encouragement_focus: 'strategy' },
    xp_awarded: 0,
    combo_multiplier: 1,
    mastery_delta: 0,
    new_badges: [],
    level_up: null,
  }
}

function mcqItem(id: number) {
  return {
    id,
    item_type: 'mcq' as const,
    bloom_tier: 2,
    points: 10,
    stem_markdown: 'Pick one',
    hint_available: false,
    payload: { kind: 'mcq' as const, multiple: false, options: [{ id: 'a', text: 'A' }] },
  }
}

const QUIZ: Quiz = {
  id: 5,
  request_id: 'req-quiz',
  title: 'Fruit quiz',
  language: 'en',
  grade_band: 'G3-5',
  subject: 'science',
  quiz_type: 'standard',
  questions: [101, 102, 103].map((id, i) => ({
    question_id: i + 1,
    ordinal: i + 1,
    points: 10,
    item: mcqItem(id),
  })),
}

function section(ordinal: number, ready = true): LessonSection {
  return {
    ordinal,
    kind: 'explanation',
    title: `Part ${ordinal}`,
    body_markdown: ready ? 'text' : null,
    gated: false,
    gen_status: ready ? 'ready' : 'pending',
    assets: [],
    items: [],
  }
}

function lesson(readyCount: number, total = 5): Lesson {
  return {
    id: 9,
    request_id: 'req-lesson',
    topic: 'Photosynthesis',
    language: 'en',
    grade_band: 'G3-5',
    subject: 'biology',
    objectives: [],
    measured_fkgl: null,
    lexile_band: null,
    estimated_duration_min: null,
    sections: Array.from({ length: total }, (_, i) => section(i, i < readyCount)),
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mocked.saveAttemptPosition.mockResolvedValue({ current_index: 0 })
  mocked.generateSection.mockImplementation(async (_id, ordinal) => section(ordinal))
})

describe('test store', () => {
  it('resumes an open attempt at the saved question with earlier answers in place', async () => {
    mocked.getQuiz.mockResolvedValue(QUIZ)
    mocked.startAttempt.mockResolvedValue({
      attempt_id: 77,
      started_at: '2026-10-12T10:00:00Z',
      resumed: true,
      current_index: 1,
      answers: [
        { item_id: 101, submitted_value: 'a', result: grade(true) },
        { item_id: 102, submitted_value: 'b', result: grade(false) },
      ],
    })
    const test = useTestStore()
    await test.load(5)

    expect(test.attemptId).toBe(77)
    expect(test.currentIndex).toBe(1)
    expect(test.current?.item.id).toBe(102)
    expect(test.results[101].is_correct).toBe(true)
    expect(test.results[102].is_correct).toBe(false) // feedback for the question on screen
    expect(test.submitted).toEqual({ 101: 'a', 102: 'b' })
    expect(test.results[103]).toBeUndefined() // the unanswered question stays unanswered
    expect(test.resumed).toBe(true)
  })

  it('starts a brand-new attempt clean, without a "welcome back"', async () => {
    mocked.getQuiz.mockResolvedValue(QUIZ)
    mocked.startAttempt.mockResolvedValue({
      attempt_id: 78,
      started_at: '2026-10-12T10:00:00Z',
      resumed: false,
      current_index: 0,
      answers: [],
    })
    const test = useTestStore()
    await test.load(5)

    expect(test.currentIndex).toBe(0)
    expect(test.results).toEqual({})
    expect(test.resumed).toBe(false)
  })

  it('tells the server each time the learner moves to the next question', async () => {
    mocked.getQuiz.mockResolvedValue(QUIZ)
    mocked.startAttempt.mockResolvedValue({
      attempt_id: 77,
      started_at: '2026-10-12T10:00:00Z',
      resumed: false,
      current_index: 0,
      answers: [],
    })
    const test = useTestStore()
    await test.load(5)

    test.next()
    test.next()
    test.next() // already on the last question — nowhere further to go
    expect(test.currentIndex).toBe(2)
    expect(mocked.saveAttemptPosition.mock.calls).toEqual([
      [77, 1],
      [77, 2],
    ])
  })

  it('re-syncs instead of failing when the question was already answered elsewhere', async () => {
    mocked.getQuiz.mockResolvedValue(QUIZ)
    mocked.startAttempt.mockResolvedValueOnce({
      attempt_id: 77,
      started_at: '2026-10-12T10:00:00Z',
      resumed: false,
      current_index: 0,
      answers: [],
    })
    const test = useTestStore()
    await test.load(5)

    // Another tab answered question 1 in the meantime: the server refuses a second answer …
    mocked.submitAnswer.mockRejectedValue(new ApiError(409, 'already answered'))
    mocked.startAttempt.mockResolvedValueOnce({
      attempt_id: 77,
      started_at: '2026-10-12T10:00:00Z',
      resumed: true,
      current_index: 0,
      answers: [{ item_id: 101, submitted_value: 'a', result: grade(true) }],
    })
    const res = await test.submit({ questionId: 101, value: 'a', latencyMs: 10, usedHint: false })

    // … and the store adopts the server's state rather than leaving the learner stuck.
    expect(res).toBeNull()
    expect(test.results[101].is_correct).toBe(true)
    expect(test.submitted[101]).toBe('a')
  })
})

describe('lesson store', () => {
  it('restores the revealed parts and the answered questions', async () => {
    mocked.getLesson.mockResolvedValue(lesson(5))
    mocked.syncLessonProgress.mockResolvedValue({
      lesson_id: 9,
      revealed_up_to: 3,
      completed: false,
      answers: [{ item_id: 201, submitted_value: 'b', result: grade(false) }],
    })
    const store = useLessonStore()
    await store.load(9)

    expect(mocked.syncLessonProgress).toHaveBeenCalledWith(9, 0) // opening never moves the boundary
    expect(store.revealedUpTo).toBe(3)
    expect(store.feedbackByItem[201].is_correct).toBe(false)
    expect(store.submittedByItem[201]).toBe('b')
    expect(store.resumed).toBe(true)
  })

  it('never reveals past a part that is not built yet', async () => {
    mocked.getLesson.mockResolvedValue(lesson(2)) // only parts 0 and 1 exist so far
    mocked.syncLessonProgress.mockResolvedValue({
      lesson_id: 9,
      revealed_up_to: 4,
      completed: false,
      answers: [],
    })
    const store = useLessonStore()
    await store.load(9)

    expect(store.revealedUpTo).toBe(1)
  })

  it('opens from the top when there is nothing to restore (or the restore call fails)', async () => {
    mocked.getLesson.mockResolvedValue(lesson(5))
    mocked.syncLessonProgress.mockRejectedValue(new ApiError(401, 'Missing X-Resume-Code'))
    const store = useLessonStore()
    await store.load(9)

    expect(store.lesson?.id).toBe(9)
    expect(store.revealedUpTo).toBe(0)
    expect(store.feedbackByItem).toEqual({})
    expect(store.resumed).toBe(false)
  })

  it('saves the new boundary each time the learner reveals the next part', async () => {
    mocked.getLesson.mockResolvedValue(lesson(5))
    mocked.syncLessonProgress.mockResolvedValue({
      lesson_id: 9,
      revealed_up_to: 1,
      completed: false,
      answers: [],
    })
    const store = useLessonStore()
    await store.load(9)
    mocked.syncLessonProgress.mockClear()

    await store.revealNext()
    expect(store.revealedUpTo).toBe(2)
    expect(mocked.syncLessonProgress).toHaveBeenCalledWith(9, 2)
  })

  it('does not carry answers over from a previously opened lesson', async () => {
    mocked.getLesson.mockResolvedValue(lesson(5))
    mocked.syncLessonProgress.mockResolvedValueOnce({
      lesson_id: 9,
      revealed_up_to: 2,
      completed: false,
      answers: [{ item_id: 201, submitted_value: 'b', result: grade(false) }],
    })
    const store = useLessonStore()
    await store.load(9)

    mocked.syncLessonProgress.mockResolvedValueOnce({
      lesson_id: 10,
      revealed_up_to: 0,
      completed: false,
      answers: [],
    })
    await store.load(10)
    expect(store.feedbackByItem).toEqual({})
    expect(store.revealedUpTo).toBe(0)
    expect(store.resumed).toBe(false)
  })
})

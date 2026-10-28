/**
 * The header's streak flame follows what the learner just finished — a graded answer (right or
 * wrong), a lesson part, a whole quiz — from the streak the server returns with it: no extra request,
 * and never rolled back by a snapshot fetched before the server committed the answer.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GamificationSnapshot, GradeResult, Lesson, StreakInfo } from '@/types/session'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      getQuiz: vi.fn(),
      startAttempt: vi.fn(),
      submitAnswer: vi.fn(),
      completeAttempt: vi.fn(),
      getLesson: vi.fn(),
      syncLessonProgress: vi.fn(),
      generateSection: vi.fn(),
      getGamification: vi.fn(),
    },
  }
})

import { api } from '@/lib/api'
import { useLessonStore } from '@/stores/lesson'
import { useSessionStore } from '@/stores/session'
import { useTestStore } from '@/stores/test'

const mocked = vi.mocked(api)

function streak(current: number, extra: Partial<StreakInfo> = {}): StreakInfo {
  return { current, longest: Math.max(current, 4), freeze_inventory: 2, is_perfect: true, frozen: false, ...extra }
}

function snapshot(current: number): GamificationSnapshot {
  return {
    level: 2,
    total_xp: 150,
    xp_to_next: 40,
    level_progress_pct: 0.5,
    streak: streak(current),
    daily_goal: 'regular',
    daily_progress_xp: 0,
    badges: [],
  }
}

function grade(over: Partial<GradeResult> = {}): GradeResult {
  return {
    is_correct: false,
    partial_credit: 0,
    correct_answer: 'a',
    fsrs_rating: 1,
    next_due: null,
    explanation: null,
    misconception: null,
    feedback: { text: 'ok', encouragement_focus: 'strategy' },
    xp_awarded: 0,
    combo_multiplier: 1,
    mastery_delta: 0,
    new_badges: [],
    level_up: null,
    ...over,
  }
}

function lesson(): Lesson {
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
    sections: [0, 1, 2].map((ordinal) => ({
      ordinal,
      kind: 'explanation',
      title: `Part ${ordinal}`,
      body_markdown: 'text',
      gated: false,
      gen_status: 'ready' as const,
      assets: [],
      items: [],
    })),
  }
}

async function startQuiz() {
  mocked.getQuiz.mockResolvedValue({
    id: 5,
    request_id: 'q',
    title: 'Quiz',
    language: 'en',
    grade_band: 'G3-5',
    subject: 'science',
    quiz_type: 'standard',
    questions: [],
  })
  mocked.startAttempt.mockResolvedValue({
    attempt_id: 77,
    started_at: '2026-09-22T18:00:00Z',
    resumed: false,
    current_index: 0,
    answers: [],
  })
  const test = useTestStore()
  await test.load(5)
  return test
}

const event = { questionId: 101, value: 'b', latencyMs: 900, usedHint: false }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  useSessionStore().gamification = snapshot(0) // e.g. back after a long break: shown as 0
})

describe('after a quiz answer', () => {
  it('a wrong answer (no XP) updates the flame without fetching the snapshot', async () => {
    const test = await startQuiz()
    mocked.submitAnswer.mockResolvedValue(grade({ streak: streak(1) }))

    await test.submit(event)

    expect(useSessionStore().gamification?.streak.current).toBe(1)
    expect(mocked.getGamification).not.toHaveBeenCalled()
  })

  it('keeps the answer’s streak even when the XP refresh returns an older snapshot', async () => {
    const test = await startQuiz()
    mocked.submitAnswer.mockResolvedValue(grade({ is_correct: true, xp_awarded: 12, streak: streak(5) }))
    mocked.getGamification.mockResolvedValue({ ...snapshot(4), total_xp: 162 }) // before the commit

    await test.submit(event)

    const session = useSessionStore()
    expect(session.gamification?.total_xp).toBe(162) // XP from the refresh …
    expect(session.gamification?.streak.current).toBe(5) // … streak from the answer itself
  })

  it('an ungraded (crisis-support) result leaves the flame alone', async () => {
    const test = await startQuiz()
    mocked.submitAnswer.mockResolvedValue(
      grade({ support: { message: 'm', resources: [], disclosure: 'd' }, streak: null }),
    )

    await test.submit(event)

    expect(useSessionStore().gamification?.streak.current).toBe(0)
  })

  it('finishing the quiz shows the streak it settled', async () => {
    const test = await startQuiz()
    mocked.completeAttempt.mockResolvedValue({ score: 0, max_score: 1, streak: streak(2) })
    mocked.getGamification.mockResolvedValue(snapshot(1)) // fetched before the server committed

    await test.complete()

    expect(useSessionStore().gamification?.streak.current).toBe(2)
  })
})

describe('after a lesson part', () => {
  it('revealing the next part updates the flame from the progress reply', async () => {
    mocked.getLesson.mockResolvedValue(lesson())
    mocked.syncLessonProgress.mockResolvedValueOnce({
      lesson_id: 9,
      revealed_up_to: 0,
      completed: false,
      answers: [],
      streak: null, // opening a lesson isn't a finished part
    })
    const store = useLessonStore()
    await store.load(9)
    expect(useSessionStore().gamification?.streak.current).toBe(0)

    mocked.syncLessonProgress.mockResolvedValueOnce({
      lesson_id: 9,
      revealed_up_to: 1,
      completed: false,
      answers: [],
      streak: streak(1),
    })
    await store.revealNext()
    await vi.waitFor(() => expect(useSessionStore().gamification?.streak.current).toBe(1))
    expect(mocked.getGamification).not.toHaveBeenCalled()
  })

  it('ignores a reply that lands after the learner left the lesson', async () => {
    mocked.getLesson.mockResolvedValue(lesson())
    mocked.syncLessonProgress.mockResolvedValueOnce({
      lesson_id: 9,
      revealed_up_to: 0,
      completed: false,
      answers: [],
    })
    const store = useLessonStore()
    await store.load(9)

    let reply: (v: unknown) => void = () => {}
    mocked.syncLessonProgress.mockReturnValueOnce(new Promise((r) => (reply = r)) as never)
    await store.revealNext()
    store.reset() // e.g. another learner took over this device
    reply({ lesson_id: 9, revealed_up_to: 1, completed: false, answers: [], streak: streak(8) })
    await Promise.resolve()
    await Promise.resolve()

    expect(useSessionStore().gamification?.streak.current).toBe(0)
  })
})

describe('applyStreak', () => {
  it('does nothing without a streak or before the snapshot has loaded', () => {
    const session = useSessionStore()
    session.applyStreak(null)
    session.applyStreak(undefined)
    expect(session.gamification?.streak.current).toBe(0)

    session.gamification = null
    session.applyStreak(streak(3))
    expect(session.gamification).toBeNull()
  })
})

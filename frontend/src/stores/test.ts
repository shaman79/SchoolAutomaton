/** Drives the interactive TestRunner: load quiz → start (or resume) attempt → grade each answer →
 *  results. The SERVER owns the attempt — the question the learner is on and every graded answer — so
 *  a refresh, a break, or another device with the same resume code picks up at the exact question.
 *  Combo/scoring come from the server GradeResult; this store mirrors per-question state + progress. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError, api } from '@/lib/api'
import type { AnswerEvent, SubmittedValue } from '@/types/question'
import type { AttemptStart, GradeResult, Quiz } from '@/types/session'

import { useSessionStore } from './session'

export const useTestStore = defineStore('test', () => {
  const quiz = ref<Quiz | null>(null)
  const attemptId = ref<number | null>(null)
  // The quiz id the persisted attempt belongs to — used to validate a restored attempt on resume.
  const quizId = ref<number | null>(null)
  const currentIndex = ref(0)
  const results = ref<Record<number, GradeResult>>({})
  // What the learner had submitted, per item id, as replayed by the server — so a restored question
  // shows their answer again, not just the verdict.
  const submitted = ref<Record<number, SubmittedValue>>({})
  // True when load() picked up an attempt that already had progress (the view greets the learner).
  const resumed = ref(false)
  const summary = ref<unknown | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const total = computed(() => quiz.value?.questions.length ?? 0)
  const current = computed(() => quiz.value?.questions[currentIndex.value] ?? null)
  const answeredCount = computed(() => Object.keys(results.value).length)
  const finished = computed(() => total.value > 0 && answeredCount.value >= total.value)

  function _apply(q: Quiz, started: AttemptStart): void {
    const res: Record<number, GradeResult> = {}
    const sub: Record<number, SubmittedValue> = {}
    for (const a of started.answers) {
      res[a.item_id] = a.result
      sub[a.item_id] = a.submitted_value
    }
    quiz.value = q
    quizId.value = q.id
    attemptId.value = started.attempt_id
    results.value = res
    submitted.value = sub
    currentIndex.value = Math.min(Math.max(0, started.current_index), Math.max(0, q.questions.length - 1))
    summary.value = null
    resumed.value = started.resumed && (started.current_index > 0 || started.answers.length > 0)
  }

  async function load(id: number): Promise<void> {
    // This tab's own copy of the open attempt (sessionStorage) paints instantly on a refresh; the
    // server's state then replaces it. Anything else is cleared first, so a previous quiz (or its
    // revealed answers) never flashes while this one loads.
    const cached =
      quizId.value === id &&
      attemptId.value != null &&
      summary.value == null &&
      quiz.value?.id === id
    if (!cached) reset()
    loading.value = !cached
    error.value = null
    try {
      // Idempotent server-side: an open attempt for this quiz is resumed (never duplicated) and comes
      // back with the learner's position + already-graded answers.
      const [q, started] = await Promise.all([api.getQuiz(id), api.startAttempt(id)])
      _apply(q, started)
    } catch (e) {
      if (cached) return // e.g. a refresh while offline: carry on with the tab's own copy
      error.value = e instanceof Error ? e.message : 'Could not load test'
      throw e
    } finally {
      loading.value = false
    }
  }

  /** Grade an answer. Resolves to null when the server had already settled this question (answered
   *  or finished in another tab/device): the store re-syncs to the server's state instead.
   *  A result carrying `support` (crisis net) was NOT graded: it is returned for the view to show,
   *  but not recorded, so the question stays unanswered and answerable. */
  async function submit(event: AnswerEvent): Promise<GradeResult | null> {
    let res: GradeResult
    try {
      res = await api.submitAnswer({ ...event, attemptId: attemptId.value })
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && quizId.value != null) {
        await load(quizId.value)
        return null
      }
      throw e
    }
    if (res.support) return res
    results.value[event.questionId] = res
    // The answer is graded and saved; a failed header refresh must not turn that into an error.
    if (res.xp_awarded) await useSessionStore().refreshGamification().catch(() => {})
    return res
  }

  function next(): void {
    if (currentIndex.value >= total.value - 1) return
    currentIndex.value += 1
    // Tell the server which question we're on now, so a refresh / break / other device resumes here.
    // Best-effort: the server never resumes behind an answered question anyway.
    if (attemptId.value != null) {
      void api.saveAttemptPosition(attemptId.value, currentIndex.value).catch(() => {})
    }
  }

  async function complete(): Promise<unknown> {
    if (attemptId.value == null) return null
    summary.value = await api.completeAttempt(attemptId.value)
    await useSessionStore().refreshGamification()
    // Release the resumable attempt so a FINISHED quiz isn't auto-resumed on a later visit (the
    // summary stays persisted for the results screen).
    attemptId.value = null
    quizId.value = null
    return summary.value
  }

  /** Wipe all quiz state — called on a learner-identity switch so a prior learner's answers (and the
   *  revealed correct answers in `results`) can't surface for the next user of a shared device. */
  function reset(): void {
    quiz.value = null
    attemptId.value = null
    quizId.value = null
    currentIndex.value = 0
    results.value = {}
    submitted.value = {}
    resumed.value = false
    summary.value = null
    loading.value = false
    error.value = null
  }

  return {
    quiz,
    attemptId,
    quizId,
    currentIndex,
    results,
    submitted,
    resumed,
    summary,
    loading,
    error,
    total,
    current,
    answeredCount,
    finished,
    load,
    submit,
    next,
    complete,
    reset,
  }
}, {
  // A same-tab cache only (instant paint on refresh; the server is the source of truth for resuming)
  // — sessionStorage, NOT localStorage: `results` and `summary` carry server-revealed correct answers
  // + explanations (SPEC §2), which must not persist across tabs/restarts or leak to the next
  // anonymous learner on a shared device. (loading/error are excluded so a refresh can't restore a
  // stuck spinner.)
  persist: {
    storage: sessionStorage,
    pick: ['quiz', 'quizId', 'attemptId', 'currentIndex', 'results', 'submitted', 'summary'],
  },
})

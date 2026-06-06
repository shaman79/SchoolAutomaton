/** Drives the interactive TestRunner: load quiz → start attempt → grade each answer → results.
 *  Combo/scoring come from the server GradeResult; this store tracks per-question state + progress. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/lib/api'
import type { AnswerEvent } from '@/types/question'
import type { GradeResult, Quiz } from '@/types/session'

import { useSessionStore } from './session'

export const useTestStore = defineStore('test', () => {
  const quiz = ref<Quiz | null>(null)
  const attemptId = ref<number | null>(null)
  // The quiz id the persisted attempt belongs to — used to validate a restored attempt on resume.
  const quizId = ref<number | null>(null)
  const currentIndex = ref(0)
  const results = ref<Record<number, GradeResult>>({})
  const summary = ref<unknown | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const total = computed(() => quiz.value?.questions.length ?? 0)
  const current = computed(() => quiz.value?.questions[currentIndex.value] ?? null)
  const answeredCount = computed(() => Object.keys(results.value).length)
  const finished = computed(() => total.value > 0 && answeredCount.value >= total.value)

  async function load(id: number): Promise<void> {
    // Resume an in-progress attempt for the SAME quiz (restored from localStorage on refresh) instead
    // of restarting: keeps answers/position AND avoids minting a duplicate server attempt.
    if (
      quizId.value === id &&
      attemptId.value != null &&
      summary.value == null &&
      quiz.value?.id === id
    ) {
      return
    }
    loading.value = true
    error.value = null
    try {
      quiz.value = await api.getQuiz(id)
      const started = await api.startAttempt(id)
      attemptId.value = started.attempt_id
      quizId.value = id
      currentIndex.value = 0
      results.value = {}
      summary.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Could not load test'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function submit(event: AnswerEvent): Promise<GradeResult> {
    const res = await api.submitAnswer({ ...event, attemptId: attemptId.value })
    results.value[event.questionId] = res
    if (res.xp_awarded) await useSessionStore().refreshGamification()
    return res
  }

  function next(): void {
    if (currentIndex.value < total.value - 1) currentIndex.value += 1
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
  // Survive a mid-quiz page refresh WITHIN the tab — sessionStorage, NOT localStorage: `results` and
  // `summary` carry server-revealed correct answers + explanations (SPEC §2), which must not persist
  // across tabs/restarts or leak to the next anonymous learner on a shared device. (loading/error are
  // excluded so a refresh can't restore a stuck spinner.)
  persist: {
    storage: sessionStorage,
    pick: ['quiz', 'quizId', 'attemptId', 'currentIndex', 'results', 'summary'],
  },
})

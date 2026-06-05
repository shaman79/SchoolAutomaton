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
    loading.value = true
    error.value = null
    try {
      quiz.value = await api.getQuiz(id)
      const started = await api.startAttempt(id)
      attemptId.value = started.attempt_id
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
    return summary.value
  }

  return {
    quiz,
    attemptId,
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
  }
})

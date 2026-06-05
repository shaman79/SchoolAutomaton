/**
 * Small shared helper for the question components (owned by F2, lives under components/questions).
 * Tracks how long the learner took to answer (drives FSRS Hard/Easy rating derivation server-side)
 * and whether a hint was revealed. Each component builds its AnswerEvent from this + its own value.
 */
import { onMounted, ref } from 'vue'

import type { AnswerEvent, SubmittedValue } from '@/types/question'

export function useAnswerTiming(questionId: () => number) {
  const startedAt = ref<number>(typeof performance !== 'undefined' ? performance.now() : Date.now())
  const usedHint = ref(false)

  onMounted(() => {
    startedAt.value = typeof performance !== 'undefined' ? performance.now() : Date.now()
  })

  function reset() {
    startedAt.value = typeof performance !== 'undefined' ? performance.now() : Date.now()
    usedHint.value = false
  }

  function markHintUsed() {
    usedHint.value = true
  }

  function latencyMs(): number {
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
    return Math.max(0, Math.round(now - startedAt.value))
  }

  /** Build the normalized event every question emits up to the test/lesson store. */
  function buildEvent(value: SubmittedValue): AnswerEvent {
    return {
      questionId: questionId(),
      value,
      latencyMs: latencyMs(),
      usedHint: usedHint.value,
    }
  }

  return { startedAt, usedHint, reset, markHintUsed, latencyMs, buildEvent }
}

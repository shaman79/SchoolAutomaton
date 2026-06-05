/** Drives the /loading screen: kicks off generation and tracks SSE progress until ready/error. */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, streamGeneration } from '@/lib/api'

export type GenStatus = 'idle' | 'queued' | 'generating' | 'ready' | 'error'

interface SectionStub {
  ordinal: number
  kind: string
  title?: string
}

export const useGenerationStore = defineStore('generation', () => {
  const status = ref<GenStatus>('idle')
  const sections = ref<SectionStub[]>([])
  const resultMode = ref<'study' | 'test' | null>(null)
  const lessonId = ref<number | null>(null)
  const quizId = ref<number | null>(null)
  const message = ref<string | null>(null)
  let es: EventSource | null = null

  async function start(requestId: string): Promise<void> {
    reset()
    status.value = 'queued'
    await api.startGeneration(requestId)
    es = streamGeneration(requestId, {
      onStatus: (d) => {
        if (d.status === 'generating') status.value = 'generating'
      },
      onPlan: (d) => {
        const list = (d as { sections?: SectionStub[] }).sections
        if (Array.isArray(list)) sections.value = list
      },
      onSection: (d) => {
        const i = sections.value.findIndex((s) => s.ordinal === d.ordinal)
        if (i >= 0) sections.value[i] = { ...sections.value[i], ...d }
        else sections.value.push(d)
      },
      onReady: (d) => {
        status.value = 'ready'
        resultMode.value = (d.mode as 'study' | 'test') ?? null
        lessonId.value = d.lesson_id ?? null
        quizId.value = d.quiz_id ?? null
      },
      onError: (d) => {
        status.value = 'error'
        message.value = d.message
      },
    })
  }

  function stop(): void {
    es?.close()
    es = null
  }
  function reset(): void {
    stop()
    status.value = 'idle'
    sections.value = []
    resultMode.value = null
    lessonId.value = null
    quizId.value = null
    message.value = null
  }

  return { status, sections, resultMode, lessonId, quizId, message, start, stop, reset }
})

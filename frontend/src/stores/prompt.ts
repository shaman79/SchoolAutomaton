/** Holds the student's prompt and the sanitizer Decision. The single entry into the learning flow. */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '@/lib/api'
import type { Decision, Mode } from '@/types/session'

export const usePromptStore = defineStore('prompt', () => {
  const raw = ref('')
  const decision = ref<Decision | null>(null)
  const submitting = ref(false)
  const error = ref<string | null>(null)

  async function submit(text: string): Promise<Decision> {
    raw.value = text
    submitting.value = true
    error.value = null
    try {
      const d = await api.submitPrompt(text)
      decision.value = d
      return d
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Something went wrong'
      throw e
    } finally {
      submitting.value = false
    }
  }

  function requestId(): string | null {
    return decision.value && 'request_id' in decision.value ? decision.value.request_id : null
  }
  function mode(): Mode | null {
    return decision.value?.type === 'proceed' ? decision.value.mode : null
  }
  function reset(): void {
    raw.value = ''
    decision.value = null
    error.value = null
  }

  return { raw, decision, submitting, error, submit, requestId, mode, reset }
})

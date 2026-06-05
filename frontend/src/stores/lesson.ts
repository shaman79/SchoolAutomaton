/** Loads and holds the current lesson for the LessonReader. */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '@/lib/api'
import type { Lesson } from '@/types/session'

export const useLessonStore = defineStore('lesson', () => {
  const lesson = ref<Lesson | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load(id: number): Promise<void> {
    loading.value = true
    error.value = null
    try {
      lesson.value = await api.getLesson(id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Could not load lesson'
      throw e
    } finally {
      loading.value = false
    }
  }

  return { lesson, loading, error, load }
})

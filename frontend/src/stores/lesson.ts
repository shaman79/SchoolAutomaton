/** Loads and holds the current lesson for the LessonReader (progressive: sections fill on demand). */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '@/lib/api'
import type { Lesson } from '@/types/session'

export const useLessonStore = defineStore('lesson', () => {
  const lesson = ref<Lesson | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  // Progressive generation: the ordinal currently being built (for a per-section spinner), and the
  // ordinal whose last build failed (so the reader can offer a retry).
  const generatingOrdinal = ref<number | null>(null)
  const failedOrdinal = ref<number | null>(null)

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

  /** Generate (or fetch, if ready) the section at `ordinal` and splice it into the lesson. */
  async function generateSection(ordinal: number): Promise<void> {
    if (!lesson.value || generatingOrdinal.value !== null) return
    generatingOrdinal.value = ordinal
    failedOrdinal.value = null
    try {
      const section = await api.generateSection(lesson.value.id, ordinal)
      const sections = lesson.value.sections
      const idx = sections.findIndex((s) => s.ordinal === ordinal)
      if (idx >= 0) sections[idx] = section
      else sections.push(section)
    } catch {
      failedOrdinal.value = ordinal
    } finally {
      generatingOrdinal.value = null
    }
  }

  return { lesson, loading, error, generatingOrdinal, failedOrdinal, load, generateSection }
})

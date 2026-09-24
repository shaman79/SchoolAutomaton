/** Transient UI state shared across views (not persisted). */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUiStore = defineStore('ui', () => {
  /** The settings panel (language, class, accessibility) — opened from the header, FAB or home. */
  const settingsOpen = ref(false)
  return { settingsOpen }
})

/** Accessibility + learning preferences. Persisted locally and applied to <html>; mirrored to the
 *  server (so they follow a resume code across devices) by the session store. */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type ThemeName = 'default' | 'highcontrast' | 'dyslexia'
export type FontName = 'lexend' | 'atkinson' | 'opendyslexic'
export type DailyGoal = 'casual' | 'regular' | 'serious' | 'intense'

export const usePrefsStore = defineStore(
  'prefs',
  () => {
    const theme = ref<ThemeName>('default')
    const font = ref<FontName>('lexend')
    const fontScale = ref(1)
    const reducedMotion = ref(false)
    const sound = ref(true)
    const locale = ref('en')
    const dailyGoal = ref<DailyGoal>('regular')

    function applyToDom() {
      const el = document.documentElement
      if (theme.value === 'default') delete el.dataset.theme
      else el.dataset.theme = theme.value
      if (font.value === 'lexend') delete el.dataset.font
      else el.dataset.font = font.value
      el.dataset.reducedMotion = String(reducedMotion.value)
      el.style.setProperty('--font-scale', String(fontScale.value))
    }

    /** Merge server-provided settings (e.g. after resume) without clobbering local-only state. */
    function hydrateFromServer(s: Partial<{
      theme: string
      font: string
      font_scale: number
      reduced_motion: boolean
      sound: boolean
      locale: string
      daily_goal: string
    }>) {
      if (s.theme) theme.value = s.theme as ThemeName
      if (s.font) font.value = s.font as FontName
      if (typeof s.font_scale === 'number') fontScale.value = s.font_scale
      if (typeof s.reduced_motion === 'boolean') reducedMotion.value = s.reduced_motion
      if (typeof s.sound === 'boolean') sound.value = s.sound
      if (s.locale) locale.value = s.locale
      if (s.daily_goal) dailyGoal.value = s.daily_goal as DailyGoal
      applyToDom()
    }

    function toServerPatch() {
      return {
        theme: theme.value,
        font: font.value,
        font_scale: fontScale.value,
        reduced_motion: reducedMotion.value,
        sound: sound.value,
        locale: locale.value,
        daily_goal: dailyGoal.value,
      }
    }

    watch([theme, font, fontScale, reducedMotion], applyToDom)

    return {
      theme,
      font,
      fontScale,
      reducedMotion,
      sound,
      locale,
      dailyGoal,
      applyToDom,
      hydrateFromServer,
      toServerPatch,
    }
  },
  { persist: true },
)

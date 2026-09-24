/** Accessibility + learning preferences. Persisted locally and applied to <html>; mirrored to the
 *  server (so they follow a resume code across devices) by the session store. */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { baseUiLocale, educationLocaleFromBrowser, setLocale } from '@/i18n'

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
    // Education-system locale (BCP-47, e.g. 'en-US') — shapes GENERATED content + its language.
    // Distinct from `locale` (the UI language). null = generic (no curriculum); resolved on boot.
    const educationLocale = ref<string | null>(null)
    // The learner's class as an exact school year (lib/grades: 1 = first grade, 0 = preschool).
    // Sent with each prompt so content fits the class when the prompt names no level. null = not set.
    const schoolYear = ref<number | null>(null)
    // A class the learner chose on THIS device that the server hasn't confirmed yet. While set, the
    // local value wins over hydration (the profile often loads only at the first prompt), and only
    // then is the class included in a settings sync — so a stale device never overwrites it.
    const schoolYearPending = ref(false)
    // Language rule: until the learner picks a language in Settings, the app follows the BROWSER
    // (re-read on every visit). Once picked, the choice is followed everywhere — UI, generated content,
    // server messages — and survives profile loads (pending until the server confirms it).
    const languageChosen = ref(false)
    const languagePending = ref(false)
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
      education_locale: string | null
      school_year: number | null
      daily_goal: string
    }>, opts: { identity?: boolean } = {}) {
      if (s.theme) theme.value = s.theme as ThemeName
      if (s.font) font.value = s.font as FontName
      if (typeof s.font_scale === 'number') fontScale.value = s.font_scale
      if (typeof s.reduced_motion === 'boolean') reducedMotion.value = s.reduced_motion
      if (typeof s.sound === 'boolean') sound.value = s.sound
      // Language: never over an unsynced local choice, never over "follow the browser" — except when
      // a learner resumes their own profile (opts.identity), whose saved language then follows them.
      if (!languagePending.value && (languageChosen.value || opts.identity) && s.education_locale) {
        educationLocale.value = s.education_locale
        locale.value = baseUiLocale(s.education_locale)
        languageChosen.value = true
      }
      // The server's class (including "not set") wins unless this device holds an unsynced choice.
      if ('school_year' in s && !schoolYearPending.value) schoolYear.value = s.school_year ?? null
      if (s.daily_goal) dailyGoal.value = s.daily_goal as DailyGoal
      applyToDom()
    }

    /** The learner picked (or cleared) their class on this device. */
    function setSchoolYear(year: number | null) {
      schoolYear.value = year
      schoolYearPending.value = true
    }

    /** The learner picked a language (education system + UI language) in Settings. */
    function setLanguage(edu: string) {
      educationLocale.value = edu
      locale.value = baseUiLocale(edu)
      languageChosen.value = true
      languagePending.value = true
    }

    /** No explicit choice yet: mirror the browser's language (called on every boot). */
    function followBrowserLanguage(tag: string | null | undefined) {
      if (languageChosen.value) return
      educationLocale.value = educationLocaleFromBrowser(tag)
      locale.value = baseUiLocale(educationLocale.value)
    }

    /** A different learner took over this device: their own settings apply, not unsynced local ones. */
    function resetForNewLearner() {
      schoolYearPending.value = false
      languagePending.value = false
    }

    function toServerPatch() {
      return {
        theme: theme.value,
        font: font.value,
        font_scale: fontScale.value,
        reduced_motion: reducedMotion.value,
        sound: sound.value,
        // Language is pushed only once chosen, so a device that merely follows its browser never
        // overwrites the learner's saved choice.
        ...(languageChosen.value ? { locale: locale.value, education_locale: educationLocale.value } : {}),
        // Only a local change is pushed (null = cleared here); otherwise the server keeps its value.
        ...(schoolYearPending.value ? { school_year: schoolYear.value } : {}),
        daily_goal: dailyGoal.value,
      }
    }

    watch([theme, font, fontScale, reducedMotion], applyToDom)
    // The UI locale ALWAYS follows the stored preference — on boot (persisted), on a settings change,
    // and after hydrateFromServer (resume). Fixes the locale resetting to English on reload/resume.
    watch(locale, (l) => setLocale(l), { immediate: true })

    return {
      theme,
      font,
      fontScale,
      reducedMotion,
      sound,
      locale,
      educationLocale,
      schoolYear,
      schoolYearPending,
      languageChosen,
      languagePending,
      dailyGoal,
      applyToDom,
      hydrateFromServer,
      setSchoolYear,
      setLanguage,
      followBrowserLanguage,
      resetForNewLearner,
      toServerPatch,
    }
  },
  { persist: true },
)

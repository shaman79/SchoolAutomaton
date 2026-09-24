/** Learner identity + gamification snapshot. Owns the resume code lifecycle (create / resume / load).
 *  No registration: a resume code is created lazily and cached in localStorage (see lib/api). */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, getResumeCode, setResumeCode } from '@/lib/api'
import type { GamificationSnapshot, ProfilePublic } from '@/types/session'

import { useGenerationStore } from './generation'
import { useLessonStore } from './lesson'
import { usePrefsStore } from './prefs'
import { useTestStore } from './test'

export const useSessionStore = defineStore('session', () => {
  const profile = ref<ProfilePublic | null>(null)
  const gamification = ref<GamificationSnapshot | null>(null)
  const resumeCode = ref<string | null>(getResumeCode())
  const ready = ref(false)
  const lastResumeCodeForDisplay = ref<string | null>(null)

  const isAuthenticated = computed(() => profile.value !== null)
  const level = computed(() => gamification.value?.level ?? 1)

  function _adopt(env: { profile: ProfilePublic; settings: unknown; gamification: GamificationSnapshot }) {
    profile.value = env.profile
    gamification.value = env.gamification
    usePrefsStore().hydrateFromServer(env.settings as Record<string, unknown>)
  }

  /** Purge per-learner content (quiz answers/results, lesson, generation) on an identity change so
   *  a prior learner's data — including revealed correct answers — never surfaces for the next user
   *  of a shared device. Prefs are intentionally NOT cleared (they re-hydrate from the new profile). */
  function clearLearnerContent() {
    useTestStore().reset()
    useLessonStore().reset()
    useGenerationStore().reset()
    try {
      sessionStorage.removeItem('test') // the persisted test-store key is the store id
    } catch {
      /* storage unavailable — refs were already reset above */
    }
  }

  /** Ensure we have a profile: load the cached resume code, or create a fresh anonymous profile. */
  async function ensureProfile(): Promise<void> {
    const prefs = usePrefsStore()
    if (resumeCode.value) {
      try {
        _adopt(await api.getMe())
        ready.value = true
        // A class picked on this device before the profile loaded is pushed up now (hydration
        // above kept it). Best-effort: the prompt itself already carries the local value.
        if (prefs.schoolYearPending) await syncPrefs().catch(() => {})
        return
      } catch {
        // The cached code is stale → we're about to become a different (fresh) learner.
        clearLearnerContent()
        setResumeCode(null)
        resumeCode.value = null
      }
    }
    const created = await api.createProfile({
      locale: prefs.locale,
      education_locale: prefs.educationLocale,
      school_year: prefs.schoolYear,
    })
    setResumeCode(created.resume_code)
    resumeCode.value = created.resume_code
    lastResumeCodeForDisplay.value = created.resume_code
    profile.value = created.profile
    // The new profile was created WITH the local class, so it is no longer pending.
    if (created.settings.school_year === prefs.schoolYear) prefs.schoolYearPending = false
    prefs.hydrateFromServer(created.settings as unknown as Record<string, unknown>)
    await refreshGamification()
    ready.value = true
  }

  async function resumeWithCode(code: string): Promise<void> {
    const env = await api.resumeProfile(code)
    // A different learner is taking over this device — drop the previous learner's content first,
    // and let their own class (even "not set") replace the previous learner's.
    clearLearnerContent()
    usePrefsStore().resetForNewLearner()
    setResumeCode(code)
    resumeCode.value = code
    _adopt(env)
    ready.value = true
  }

  async function refreshGamification(): Promise<void> {
    gamification.value = await api.getGamification()
    if (profile.value) profile.value.total_xp = gamification.value.total_xp
  }

  /** Push current local prefs to the server so they follow the resume code. */
  async function syncPrefs(): Promise<void> {
    if (!isAuthenticated.value) return
    const prefs = usePrefsStore()
    const patch = prefs.toServerPatch()
    await api.updateSettings(patch)
    // Confirmed — unless the learner changed the class again while the request was in flight.
    if ('school_year' in patch && patch.school_year === prefs.schoolYear) {
      prefs.schoolYearPending = false
    }
  }

  function forget(): void {
    clearLearnerContent()
    setResumeCode(null)
    resumeCode.value = null
    profile.value = null
    gamification.value = null
    ready.value = false
  }

  return {
    profile,
    gamification,
    resumeCode,
    ready,
    lastResumeCodeForDisplay,
    isAuthenticated,
    level,
    ensureProfile,
    resumeWithCode,
    refreshGamification,
    syncPrefs,
    forget,
  }
})

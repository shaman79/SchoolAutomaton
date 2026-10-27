/** Learner identity + gamification snapshot. Owns the resume code lifecycle (create / resume / load).
 *  No registration: a resume code is created lazily and cached in localStorage (see lib/api).
 *
 *  THE STORED CODE IS THE CHILD'S PROGRESS. It is dropped only when the server definitively says it
 *  doesn't know it (401 from GET /profiles/me). Any other failure — offline, a timeout, a 502 while a
 *  deploy restarts the server — keeps the code, retries briefly, and then reports `unreachable` so
 *  the UI can offer "try again". A new profile is created only when the device holds no code. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, getResumeCode, setResumeCode } from '@/lib/api'
import { ApiError } from '@/lib/apiError'
import { isTransient } from '@/lib/errors'
import { clearReadingAnchor } from '@/lib/readingAnchor'
import { withRetry } from '@/lib/retry'
import type { GamificationSnapshot, ProfileEnvelope, ProfilePublic } from '@/types/session'

import { useGenerationStore } from './generation'
import { useLessonStore } from './lesson'
import { usePrefsStore } from './prefs'
import { useTestStore } from './test'

/** Pauses before re-trying GET /profiles/me after a transient failure (3 attempts in total). */
export const PROFILE_RETRY_DELAYS_MS = [600, 1800] as const

/** The only answer that proves a stored code is gone for good. */
function isUnknownCode(e: unknown): boolean {
  return e instanceof ApiError && e.status === 401
}

/** Compare codes the way the server does (case, dashes/spaces and look-alike letters ignored). */
export function normalizeResumeCode(code: string): string {
  return code
    .trim()
    .toUpperCase()
    .replace(/[\s-]/g, '')
    .replace(/[IL]/g, '1')
    .replace(/O/g, '0')
    .replace(/U/g, 'V')
}

/** "k7qf2m9x" -> "K7QF-2M9X" for display/storage; anything unusual is kept as typed (uppercased). */
export function formatResumeCode(code: string): string {
  const compact = code.trim().toUpperCase().replace(/[\s-]/g, '')
  return /^[0-9A-Z]{8}$/.test(compact)
    ? `${compact.slice(0, 4)}-${compact.slice(4)}`
    : code.trim().toUpperCase()
}

export const useSessionStore = defineStore('session', () => {
  const profile = ref<ProfilePublic | null>(null)
  const gamification = ref<GamificationSnapshot | null>(null)
  const resumeCode = ref<string | null>(getResumeCode())
  const ready = ref(false)
  const lastResumeCodeForDisplay = ref<string | null>(null)
  /** The stored code's profile couldn't be loaded (offline / server down). The code is kept; the UI
   *  shows a friendly "can't reach the server" state with a Retry (see ConnectionBanner). */
  const unreachable = ref(false)

  const isAuthenticated = computed(() => profile.value !== null)
  const level = computed(() => gamification.value?.level ?? 1)

  // Bumped whenever the learner on this device changes (resume with another code, forget). A profile
  // load that started before the change must not adopt its (previous learner's) answer afterwards.
  let identityEpoch = 0
  // One ensureProfile at a time, so a double tap can never create two profiles.
  let ensuring: Promise<void> | null = null

  function _adopt(
    env: { profile: ProfilePublic; settings: unknown; gamification: GamificationSnapshot },
    opts: { identity?: boolean } = {},
  ) {
    profile.value = env.profile
    gamification.value = env.gamification
    usePrefsStore().hydrateFromServer(env.settings as Record<string, unknown>, opts)
  }

  /** Purge per-learner content (quiz answers/results, lesson, generation) on an identity change so
   *  a prior learner's data — including revealed correct answers — never surfaces for the next user
   *  of a shared device. Prefs are intentionally NOT cleared (they re-hydrate from the new profile). */
  function clearLearnerContent() {
    useTestStore().reset()
    useLessonStore().reset()
    useGenerationStore().reset()
    clearReadingAnchor() // the previous learner's reading spot on this device
    try {
      sessionStorage.removeItem('test') // the persisted test-store key is the store id
    } catch {
      /* storage unavailable — refs were already reset above */
    }
  }

  /** GET /profiles/me, re-tried a couple of times on a blip (offline, timeout, 5xx). */
  function _fetchMe(): Promise<ProfileEnvelope> {
    return withRetry(() => api.getMe(), {
      delays: PROFILE_RETRY_DELAYS_MS,
      shouldRetry: isTransient,
    })
  }

  /** Load the stored code's profile. Resolves 'loaded', 'unknown' (the server said 401) or
   *  'superseded' (the learner changed meanwhile); for anything else it flags `unreachable` and
   *  rejects. Never drops the code and never creates a profile. */
  async function _loadStored(): Promise<'loaded' | 'unknown' | 'superseded'> {
    const epoch = identityEpoch
    let env: ProfileEnvelope
    try {
      env = await _fetchMe()
    } catch (e) {
      if (epoch !== identityEpoch) return 'superseded'
      if (isUnknownCode(e)) {
        unreachable.value = false
        return 'unknown'
      }
      unreachable.value = true
      throw e
    }
    if (epoch !== identityEpoch) return 'superseded'
    _adopt(env)
    ready.value = true
    unreachable.value = false
    // A class picked on this device before the profile loaded is pushed up now (hydration above
    // kept it). Best-effort: the prompt itself already carries the local value.
    const prefs = usePrefsStore()
    if (prefs.schoolYearPending || prefs.languagePending) await syncPrefs().catch(() => {})
    return 'loaded'
  }

  /** Ensure we have a profile: load the stored code's profile, or — only when this device holds no
   *  code, or the server says the code is unknown — create a fresh anonymous one. When the server
   *  can't be reached it rejects and KEEPS the code; the caller offers a friendly retry. */
  function ensureProfile(): Promise<void> {
    if (!ensuring) {
      ensuring = _ensureProfile().finally(() => {
        ensuring = null
      })
    }
    return ensuring
  }

  async function _ensureProfile(): Promise<void> {
    if (resumeCode.value) {
      const outcome = await _loadStored() // rejects when unreachable — the code stays
      if (outcome !== 'unknown') return
      // The server definitively doesn't know this code → we're about to become a fresh learner.
      clearLearnerContent()
      setResumeCode(null)
      resumeCode.value = null
    }
    const prefs = usePrefsStore()
    const epoch = identityEpoch
    const created = await api.createProfile({
      locale: prefs.locale,
      education_locale: prefs.educationLocale,
      school_year: prefs.schoolYear,
    })
    // A code was adopted (resume screen) while this was in flight: that learner wins.
    if (epoch !== identityEpoch || resumeCode.value) return
    setResumeCode(created.resume_code)
    resumeCode.value = created.resume_code
    lastResumeCodeForDisplay.value = created.resume_code
    profile.value = created.profile
    unreachable.value = false
    // The new profile was created WITH the local class, so it is no longer pending.
    if (created.settings.school_year === prefs.schoolYear) prefs.schoolYearPending = false
    if (created.settings.education_locale === prefs.educationLocale) prefs.languagePending = false
    prefs.hydrateFromServer(created.settings as unknown as Record<string, unknown>)
    ready.value = true
    await refreshGamification().catch(() => {}) // the header fills in after the next answer anyway
  }

  /** App boot with a stored code: load that learner's profile (settings, progress) right away instead
   *  of at the first prompt. Never creates a profile and never drops the code (a 401 is left to the
   *  first prompt's ensureProfile); a connection problem sets `unreachable`. */
  async function loadExisting(): Promise<void> {
    if (!resumeCode.value || profile.value) return
    await _loadStored().catch(() => {})
  }

  /** "Try again" from the can't-reach-the-server state. Resolves false while still unreachable. */
  async function reconnect(): Promise<boolean> {
    if (!resumeCode.value) {
      unreachable.value = false
      return true
    }
    try {
      await _loadStored()
      return true
    } catch {
      return false
    }
  }

  async function resumeWithCode(code: string): Promise<void> {
    const env = await api.resumeProfile(code)
    // A different learner is taking over this device — drop the previous learner's content first,
    // and let their own class (even "not set") replace the previous learner's. Any profile load
    // still in flight for the previous code is ignored when it lands (epoch).
    identityEpoch += 1
    clearLearnerContent()
    usePrefsStore().resetForNewLearner()
    const formatted = formatResumeCode(code)
    setResumeCode(formatted)
    resumeCode.value = formatted
    lastResumeCodeForDisplay.value = null // a code created here earlier is not this learner's
    unreachable.value = false
    _adopt(env, { identity: true })
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
    if ('education_locale' in patch && patch.education_locale === prefs.educationLocale) {
      prefs.languagePending = false
    }
  }

  function forget(): void {
    identityEpoch += 1
    clearLearnerContent()
    setResumeCode(null)
    resumeCode.value = null
    lastResumeCodeForDisplay.value = null
    unreachable.value = false
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
    unreachable,
    isAuthenticated,
    level,
    ensureProfile,
    loadExisting,
    reconnect,
    resumeWithCode,
    refreshGamification,
    syncPrefs,
    forget,
  }
})

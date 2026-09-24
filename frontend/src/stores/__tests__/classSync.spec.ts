/**
 * The class setting ("Moje třída") across profile loads, syncs and learner changes. The profile is
 * loaded lazily (at the first prompt), so a class picked earlier must survive that load, and a
 * device must never push a class it didn't change itself.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', () => ({
  api: {
    getMe: vi.fn(),
    updateSettings: vi.fn(),
    resumeProfile: vi.fn(),
    createProfile: vi.fn(),
    getGamification: vi.fn(),
  },
  getResumeCode: vi.fn(() => 'ABCD-EFGH'),
  setResumeCode: vi.fn(),
}))

import { api } from '@/lib/api'
import { usePrefsStore } from '@/stores/prefs'
import { useSessionStore } from '@/stores/session'

function envelope(schoolYear: number | null) {
  return {
    profile: { id: 1, display_name: null, total_xp: 0, level: 1, age_band: 'unknown', primary_language: 'cs', created_at: null },
    settings: { theme: 'default', locale: 'cs', education_locale: 'cs-CZ', school_year: schoolYear },
    gamification: { level: 1, total_xp: 0, xp_to_next: 100, level_progress_pct: 0, daily_goal: 'regular', daily_progress_xp: 0, badges: [],
      streak: { current: 0, longest: 0, freeze_inventory: 2, is_perfect: true, frozen: false } },
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  ;(api.updateSettings as Mock).mockResolvedValue({})
})

describe('class setting sync', () => {
  it('keeps a class picked before the profile loaded, then pushes it up', async () => {
    const prefs = usePrefsStore()
    const session = useSessionStore()
    ;(api.getMe as Mock).mockResolvedValue(envelope(4)) // server still has 4. třída
    prefs.setSchoolYear(5)

    await session.ensureProfile() // the lazy load at the first prompt

    expect(prefs.schoolYear).toBe(5)
    expect(api.updateSettings).toHaveBeenCalledWith(expect.objectContaining({ school_year: 5 }))
    expect(prefs.schoolYearPending).toBe(false)
  })

  it('adopts the server class, including "not set", when nothing changed locally', async () => {
    const prefs = usePrefsStore()
    prefs.schoolYear = 7 // e.g. cleared on another device since
    ;(api.getMe as Mock).mockResolvedValue(envelope(null))

    await useSessionStore().ensureProfile()

    expect(prefs.schoolYear).toBeNull()
    expect(api.updateSettings).not.toHaveBeenCalled()
  })

  it('never pushes a class this device did not change', async () => {
    const prefs = usePrefsStore()
    const session = useSessionStore()
    ;(api.getMe as Mock).mockResolvedValue(envelope(4))
    await session.ensureProfile()

    prefs.theme = 'dyslexia'
    await session.syncPrefs()

    const patch = (api.updateSettings as Mock).mock.calls.at(-1)![0]
    expect(patch).not.toHaveProperty('school_year')
    expect(patch.theme).toBe('dyslexia')
  })

  it('pushes an explicit clear', async () => {
    const prefs = usePrefsStore()
    const session = useSessionStore()
    ;(api.getMe as Mock).mockResolvedValue(envelope(4))
    await session.ensureProfile()

    prefs.setSchoolYear(null)
    await session.syncPrefs()

    expect(api.updateSettings).toHaveBeenLastCalledWith(expect.objectContaining({ school_year: null }))
    expect(prefs.schoolYearPending).toBe(false)
  })

  it('gives a learner resuming on a shared device their own class and language', async () => {
    const prefs = usePrefsStore()
    prefs.setSchoolYear(3) // the previous learner's class, never synced
    prefs.setLanguage('en-GB') // and their language
    ;(api.resumeProfile as Mock).mockResolvedValue(envelope(null)) // this learner: cs-CZ, no class

    await useSessionStore().resumeWithCode('WXYZ-2345')

    expect(prefs.schoolYear).toBeNull()
    expect(prefs.schoolYearPending).toBe(false)
    expect(prefs.educationLocale).toBe('cs-CZ')
    expect(prefs.locale).toBe('cs')
  })
})

describe('language: browser until chosen, then the choice everywhere', () => {
  it('follows the browser while nothing is chosen, and ignores the server copy', async () => {
    const prefs = usePrefsStore()
    prefs.followBrowserLanguage('en-GB')
    expect([prefs.educationLocale, prefs.locale]).toEqual(['en-GB', 'en'])

    ;(api.getMe as Mock).mockResolvedValue(envelope(null)) // server copy says cs-CZ
    await useSessionStore().ensureProfile()
    expect(prefs.educationLocale).toBe('en-GB')
    // …and a sync doesn't overwrite the learner's saved language with the browser's.
    await useSessionStore().syncPrefs()
    expect((api.updateSettings as Mock).mock.calls.at(-1)![0]).not.toHaveProperty('education_locale')
  })

  it('once chosen, the browser no longer decides and the choice survives the profile load', async () => {
    const prefs = usePrefsStore()
    prefs.setLanguage('cs-CZ')
    prefs.followBrowserLanguage('en-US') // next visit on an English browser
    expect([prefs.educationLocale, prefs.locale]).toEqual(['cs-CZ', 'cs'])

    const other = envelope(null)
    other.settings.education_locale = 'en-US'
    other.settings.locale = 'en'
    ;(api.getMe as Mock).mockResolvedValue(other) // stale server copy
    await useSessionStore().ensureProfile()

    expect(prefs.educationLocale).toBe('cs-CZ')
    expect(api.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ education_locale: 'cs-CZ', locale: 'cs' }),
    )
    expect(prefs.languagePending).toBe(false)
  })
})

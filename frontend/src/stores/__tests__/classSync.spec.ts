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

  it('gives a learner resuming on a shared device their own class and first-run card', async () => {
    const prefs = usePrefsStore()
    prefs.setSchoolYear(3) // the previous learner's class, never synced
    prefs.gradePromptDismissed = true
    ;(api.resumeProfile as Mock).mockResolvedValue(envelope(null))

    await useSessionStore().resumeWithCode('WXYZ-2345')

    expect(prefs.schoolYear).toBeNull()
    expect(prefs.schoolYearPending).toBe(false)
    expect(prefs.gradePromptDismissed).toBe(false)
  })
})

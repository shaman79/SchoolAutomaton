/**
 * The stored resume code is the child's progress. Only the server saying "unknown code" (401) may
 * replace it; a blip (offline, timeout, 502 during a deploy) must keep it, retry, and report
 * "can't reach the server" — never quietly start a brand-new empty profile.
 */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

const stored = vi.hoisted(() => ({ code: null as string | null }))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      getMe: vi.fn(),
      createProfile: vi.fn(),
      resumeProfile: vi.fn(),
      getGamification: vi.fn(),
      updateSettings: vi.fn(),
    },
    getResumeCode: () => stored.code,
    setResumeCode: vi.fn((c: string | null) => {
      stored.code = c
    }),
  }
})

import { ApiError, NETWORK_ERROR_STATUS, api } from '@/lib/api'
import { formatResumeCode, normalizeResumeCode, useSessionStore } from '@/stores/session'

const mocked = api as unknown as Record<string, Mock>

function envelope(id: number, xp = 0) {
  return {
    profile: { id, display_name: null, total_xp: xp, level: 1, age_band: 'unknown', primary_language: 'cs', created_at: null },
    settings: { theme: 'default', locale: 'cs', education_locale: 'cs-CZ', school_year: null },
    gamification: {
      level: 1, total_xp: xp, xp_to_next: 100, level_progress_pct: 0, daily_goal: 'regular', daily_progress_xp: 0, badges: [],
      streak: { current: 3, longest: 3, freeze_inventory: 2, is_perfect: true, frozen: false },
    },
  }
}
const created = {
  resume_code: 'NEW9-CODE',
  profile: envelope(2).profile,
  settings: { ...envelope(2).settings },
}

const offline = () => new ApiError(NETWORK_ERROR_STATUS, 'Network request failed', 'network')

beforeEach(() => {
  vi.useFakeTimers()
  stored.code = 'OLD1-CODE'
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mocked.createProfile.mockResolvedValue(created)
  mocked.getGamification.mockResolvedValue(envelope(2).gamification)
  mocked.updateSettings.mockResolvedValue({})
})
afterEach(() => vi.useRealTimers())

/** Run a store call to completion while letting its retry pauses elapse. */
async function settle<T>(p: Promise<T>): Promise<T> {
  const caught = p.catch((e) => e)
  await vi.runAllTimersAsync()
  return caught as Promise<T>
}

describe('ensureProfile', () => {
  it('keeps the code (and creates nothing) when the server is unreachable, after retrying', async () => {
    mocked.getMe.mockRejectedValue(offline())
    const s = useSessionStore()

    const result = await settle(s.ensureProfile())

    expect(result).toBeInstanceOf(ApiError) // the caller shows a friendly retry
    expect(mocked.getMe).toHaveBeenCalledTimes(3) // 1 + 2 short retries
    expect(mocked.createProfile).not.toHaveBeenCalled()
    expect(s.resumeCode).toBe('OLD1-CODE')
    expect(stored.code).toBe('OLD1-CODE')
    expect(s.unreachable).toBe(true)
  })

  it('a 502 while a deploy restarts the server is a blip too', async () => {
    mocked.getMe.mockRejectedValue(new ApiError(502, 'Bad Gateway'))
    const s = useSessionStore()
    await settle(s.ensureProfile())
    expect(mocked.createProfile).not.toHaveBeenCalled()
    expect(s.resumeCode).toBe('OLD1-CODE')
  })

  it('rides out a single blip and loads the learner', async () => {
    mocked.getMe.mockRejectedValueOnce(offline()).mockResolvedValueOnce(envelope(1, 420))
    const s = useSessionStore()
    await settle(s.ensureProfile())
    expect(s.profile?.total_xp).toBe(420)
    expect(s.unreachable).toBe(false)
    expect(mocked.createProfile).not.toHaveBeenCalled()
  })

  it('replaces the code only when the server says it is unknown (401)', async () => {
    mocked.getMe.mockRejectedValue(new ApiError(401, 'Unknown resume code'))
    const s = useSessionStore()
    await settle(s.ensureProfile())
    expect(mocked.getMe).toHaveBeenCalledTimes(1) // a definitive answer is not retried
    expect(mocked.createProfile).toHaveBeenCalledTimes(1)
    expect(s.resumeCode).toBe('NEW9-CODE')
    expect(s.lastResumeCodeForDisplay).toBe('NEW9-CODE')
  })

  it('other refusals (e.g. 403) keep the code too', async () => {
    mocked.getMe.mockRejectedValue(new ApiError(403, 'Forbidden'))
    const s = useSessionStore()
    await settle(s.ensureProfile())
    expect(mocked.createProfile).not.toHaveBeenCalled()
    expect(s.resumeCode).toBe('OLD1-CODE')
  })

  it('creates a profile on a device with no code — once, however often it is called', async () => {
    stored.code = null
    const s = useSessionStore()
    await settle(Promise.all([s.ensureProfile(), s.ensureProfile()]))
    expect(mocked.createProfile).toHaveBeenCalledTimes(1)
    expect(s.resumeCode).toBe('NEW9-CODE')
  })
})

describe('loadExisting / reconnect', () => {
  it('a failed boot load keeps the code, creates nothing and flags "unreachable"', async () => {
    mocked.getMe.mockRejectedValue(offline())
    const s = useSessionStore()
    await settle(s.loadExisting())
    expect(s.unreachable).toBe(true)
    expect(s.resumeCode).toBe('OLD1-CODE')
    expect(mocked.createProfile).not.toHaveBeenCalled()
  })

  it('a 401 at boot is left alone (no drop, no create)', async () => {
    mocked.getMe.mockRejectedValue(new ApiError(401, 'Unknown resume code'))
    const s = useSessionStore()
    await settle(s.loadExisting())
    expect(s.resumeCode).toBe('OLD1-CODE')
    expect(mocked.createProfile).not.toHaveBeenCalled()
    expect(s.unreachable).toBe(false)
  })

  it('"Try again" loads the learner and clears the state', async () => {
    mocked.getMe.mockRejectedValue(offline())
    const s = useSessionStore()
    await settle(s.loadExisting())
    mocked.getMe.mockReset().mockResolvedValue(envelope(1, 99))
    expect(await settle(s.reconnect())).toBe(true)
    expect(s.unreachable).toBe(false)
    expect(s.profile?.id).toBe(1)
  })
})

describe('resumeWithCode', () => {
  it('a slow boot load of the previous code cannot overwrite the learner who just resumed', async () => {
    let releaseOld!: (v: unknown) => void
    mocked.getMe.mockReturnValue(new Promise((r) => (releaseOld = r)))
    mocked.resumeProfile.mockResolvedValue(envelope(7, 700))
    const s = useSessionStore()

    const boot = s.loadExisting() // in flight with OLD1-CODE
    await s.resumeWithCode('k7qf2m9x')
    releaseOld(envelope(1, 5)) // the old learner's answer lands late
    await settle(boot)

    expect(s.profile?.id).toBe(7)
    expect(s.resumeCode).toBe('K7QF-2M9X')
  })

  it('clears a previously created code from the "save your code" display', async () => {
    stored.code = null
    const s = useSessionStore()
    await settle(s.ensureProfile())
    expect(s.lastResumeCodeForDisplay).toBe('NEW9-CODE')
    mocked.resumeProfile.mockResolvedValue(envelope(7))
    await s.resumeWithCode('ABCD-EFGH')
    expect(s.lastResumeCodeForDisplay).toBeNull()
  })
})

describe('code helpers', () => {
  it('compare codes the way the server does', () => {
    expect(normalizeResumeCode(' k7qf-2m9x ')).toBe(normalizeResumeCode('K7QF2M9X'))
    expect(normalizeResumeCode('ABOL-IUXX')).toBe('AB011VXX')
    expect(formatResumeCode('k7qf2m9x')).toBe('K7QF-2M9X')
    expect(formatResumeCode('K7QF-2M9X')).toBe('K7QF-2M9X')
  })
})

/**
 * Today's goal: the target is the server's (an older server falls back to the old table), and the
 * moment an answer completes it is said once a day — not on a reload that finds it already complete.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { getGamification: vi.fn() } }
})

import { toast, toasts } from '@/components/common/useToasts'
import { i18n } from '@/i18n'
import { api } from '@/lib/api'
import { dailyGoal } from '@/lib/dailyGoal'
import { useSessionStore } from '@/stores/session'
import type { GamificationSnapshot } from '@/types/session'

const getGamification = vi.mocked(api.getGamification)

function snap(xp: number, goal?: number): GamificationSnapshot {
  return {
    level: 1, total_xp: xp, xp_to_next: 50, level_progress_pct: 10,
    streak: { current: 1, longest: 1, freeze_inventory: 0, is_perfect: true, frozen: false },
    daily_goal: 'regular', daily_progress_xp: xp, daily_goal_xp: goal, badges: [],
  }
}
const goalToasts = () => toasts.items.filter((x) => x.message === i18n.global.t('gamification.daily_goal_reached'))

beforeEach(() => {
  setActivePinia(createPinia())
  for (const x of [...toasts.items]) toast.dismiss(x.id)
  localStorage.removeItem('sa_goal_day')
})

describe('dailyGoal', () => {
  it("uses the server's target, else the old table", () => {
    expect(dailyGoal(snap(50, 100))).toEqual({ earned: 50, goal: 100, complete: false })
    expect(dailyGoal(snap(60))).toEqual({ earned: 60, goal: 60, complete: true })
    expect(dailyGoal(null)).toEqual({ earned: 0, goal: 60, complete: false })
  })
})

describe('reaching the goal', () => {
  it('is said when an answer completes it, once a day', async () => {
    const session = useSessionStore()
    session.gamification = snap(50, 60)
    getGamification.mockResolvedValue(snap(65, 60))
    await session.refreshGamification()
    expect(goalToasts()).toHaveLength(1)
    // Another tab, or another crossing later the same day: not again.
    session.gamification = snap(55, 60)
    await session.refreshGamification()
    expect(goalToasts()).toHaveLength(1)
  })

  it('is not said when a reload finds it already complete', async () => {
    const session = useSessionStore()
    getGamification.mockResolvedValue(snap(80, 60))
    await session.refreshGamification() // first read: nothing to compare with
    expect(goalToasts()).toHaveLength(0)
  })
})

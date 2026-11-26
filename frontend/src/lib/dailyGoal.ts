/** Today's goal: XP earned today against the target for the learner's daily_goal. The server names
 *  the target (snapshot.daily_goal_xp); the table is only the fallback for an older server. */
import type { GamificationSnapshot } from '@/types/session'

const FALLBACK_GOAL_XP: Record<string, number> = { casual: 30, regular: 60, serious: 120, intense: 200 }

export interface DailyGoal {
  earned: number
  goal: number
  complete: boolean
}

export function dailyGoal(snap: GamificationSnapshot | null | undefined): DailyGoal {
  const earned = Math.max(0, snap?.daily_progress_xp ?? 0)
  const goal =
    snap?.daily_goal_xp && snap.daily_goal_xp > 0
      ? snap.daily_goal_xp
      : FALLBACK_GOAL_XP[snap?.daily_goal ?? 'regular'] ?? FALLBACK_GOAL_XP.regular
  return { earned, goal, complete: earned >= goal }
}

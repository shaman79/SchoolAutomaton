/**
 * "Continue where you left off" can be hidden from Home ON THIS DEVICE (×): a lesson the learner
 * considers done — or simply doesn't want — shouldn't sit there every visit. Hidden until they work
 * on it again (its last activity moves past the moment it was hidden); it stays in "My lessons"
 * meanwhile. Only an id and a time are kept, for the one most recently hidden.
 */
import type { LearningSessionSummary } from '@/types/session'

const KEY = 'sa_hidden_continue'

interface Hidden {
  id: string
  /** The session's last activity when it was hidden (ms); null when the server gave none. */
  at: number | null
}

function activity(s: LearningSessionSummary): number | null {
  const ms = Date.parse(s.progress?.last_active_at ?? '')
  return Number.isNaN(ms) ? null : ms
}

export function hideContinue(s: LearningSessionSummary): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ id: s.request_id, at: activity(s) } satisfies Hidden))
  } catch {
    /* storage unavailable — hidden for this visit only */
  }
}

export function isContinueHidden(s: LearningSessionSummary): boolean {
  try {
    const h = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<Hidden> | null
    if (!h || h.id !== s.request_id) return false
    const now = activity(s)
    // Worked on since it was hidden → it is current again.
    return !(now !== null && typeof h.at === 'number' && now > h.at)
  } catch {
    return false
  }
}

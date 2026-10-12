/**
 * Remembers where in a lesson the learner was reading ON THIS DEVICE — the part under the top of the
 * screen and how far into it — so a refresh or a return visit lands on the very same line. Finer than
 * the server's per-part position (which is what carries across devices), and it holds no lesson
 * content: only ids and pixel offsets, for the most recently read lesson.
 */

const KEY = 'sa_reading_anchor'

export interface ReadingAnchor {
  lessonId: number
  /** The reveal boundary when this was saved. If it differs now, the learner has since moved on
   *  somewhere else and this spot is stale. */
  revealedUpTo: number
  /** Ordinal of the part under the top edge of the viewport; null = still above the first part. */
  ordinal: number | null
  /** Pixels scrolled into that part (or from the top of the page when `ordinal` is null). */
  offset: number
}

export function saveReadingAnchor(anchor: ReadingAnchor): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(anchor))
  } catch {
    /* storage unavailable — the server's per-part position still applies */
  }
}

export function loadReadingAnchor(lessonId: number): ReadingAnchor | null {
  try {
    const a = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<ReadingAnchor> | null
    if (
      a &&
      a.lessonId === lessonId &&
      Number.isInteger(a.revealedUpTo) &&
      (a.ordinal === null || Number.isInteger(a.ordinal)) &&
      Number.isFinite(a.offset)
    ) {
      return a as ReadingAnchor
    }
  } catch {
    /* unreadable — treat as absent */
  }
  return null
}

export function clearReadingAnchor(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* storage unavailable */
  }
}

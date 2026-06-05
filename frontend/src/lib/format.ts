/** Small presentation helpers shared across views. */

/**
 * Turn a raw subject key into a human-readable label. Subjects are an open, model-generated string
 * field stored as snake_case / kebab-case identifiers (e.g. "language_arts"), so we humanize them
 * generically — split on separators and Title Case — rather than maintain a closed translation map.
 * "language_arts" → "Language Arts", "computer-science" → "Computer Science".
 */
export function humanizeSubject(subject: string | null | undefined): string {
  if (!subject) return ''
  return subject
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\b\p{L}/gu, (c) => c.toUpperCase())
}

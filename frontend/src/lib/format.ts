/** Small presentation helpers shared across views. */

import { i18n } from '@/i18n'

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

/**
 * The subject's name in the UI language — for the backend's known subjects the name a learner knows
 * from school ("language_arts" → "Český jazyk" in Czech), otherwise the generic humanized key.
 */
export function subjectLabel(subject: string | null | undefined): string {
  if (!subject) return ''
  const key = `subjects.${subject.trim().toLowerCase().replace(/-/g, '_')}`
  return i18n.global.te(key) ? i18n.global.t(key) : humanizeSubject(subject)
}

/**
 * Parse a typed numeric answer. Spaces (incl. no-break / thin spaces) group thousands, as Czech
 * pupils write them ("12 500"). The comma is the decimal mark ("3,5"), except for English input
 * written with comma thousands groups ("12,500"). Returns null for anything that isn't a number yet.
 */
export function parseNumericAnswer(raw: string, locale = ''): number | null {
  // JS \s already covers the no-break (U+00A0) and narrow no-break (U+202F) spaces.
  let s = raw.trim().replace(/\s/g, '')
  if (locale.startsWith('en') && /^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) s = s.replace(/,/g, '')
  s = s.replace(',', '.')
  if (s === '' || s === '-' || s === '.' || s === '-.') return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/** A number the way the UI language writes it (Czech: "3,5" and "12 500"). */
export function formatNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(value)
}

/** Small presentation helpers shared across views. */

import { i18n } from '@/i18n'
import type { LearningSessionSummary } from '@/types/session'

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

/**
 * A learner's saved position in a lesson/quiz as a short label — "Part 5 of 12", "Question 4 of 10",
 * or "Completed". Null when they haven't opened it yet (nothing to say).
 */
export function progressLabel(
  session: Pick<LearningSessionSummary, 'mode' | 'progress'>,
): string | null {
  const p = session.progress
  if (!p) return null
  if (p.completed) return i18n.global.t('progress.completed')
  return i18n.global.t(session.mode === 'test' ? 'progress.question' : 'progress.part', {
    current: p.position,
    total: p.total,
  })
}

/**
 * When something happened, as a parent reads it: "today", "yesterday", else a short date ("3. 11.").
 * Days are the viewer's own calendar days. Empty for a missing/garbled time.
 */
export function dayLabel(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ''
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return ''
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((day(now) - day(when)) / 86_400_000)
  if (diff <= 0) return i18n.global.t('parent.today') // a clock a little ahead still says "today"
  if (diff === 1) return i18n.global.t('parent.yesterday')
  return i18n.global.d(when, 'day')
}


/** Content words of a title, for comparing two phrasings ("na", "po", "of" say nothing). */
function contentWords(text: string): string[] {
  return (text.toLowerCase().match(/\p{L}{3,}/gu) ?? []).filter(Boolean)
}

/**
 * A lesson/quiz title (or topic name) for display. Lesson titles are the topic phrase the request was
 * understood as, and older ones can read "zlomky na obrázcích (vysvětlení zlomků pomocí obrázků)":
 *   - a note in brackets at the end that only restates the title — or glosses it, "X (Czech
 *     spelling: words after X)" — is dropped; one that adds something ("Shakespeare (Romeo a
 *     Julie)", "násobilka (6 a 7)") stays;
 *   - the first letter is capitalized when the first word is an ordinary lowercase word ("pH",
 *     "iPhone", a lone "x" are left alone).
 */
export function displayTitle(raw: string | null | undefined): string {
  let s = (raw ?? '').trim().replace(/\s+/g, ' ')
  const m = s.match(/^(.*\p{L}.*?)\s*\(([^()]+)\)$/u)
  if (m) {
    const [, main, note] = m
    const mainWords = contentWords(main)
    const noteStems = contentWords(note).map((w) => w.slice(0, 4))
    const restated =
      mainWords.length > 0 &&
      mainWords.filter((w) => noteStems.includes(w.slice(0, 4))).length * 2 >= mainWords.length
    const gloss = note.includes(':') && !/\d/.test(note)
    if (restated || gloss) s = main.trim()
  }
  const first = s.split(' ')[0] ?? ''
  if (/^\p{Ll}{2,}$/u.test(first.replace(/-/g, ''))) s = s.charAt(0).toUpperCase() + s.slice(1)
  return s
}

/**
 * A knowledge topic's name for display. Older topics may carry their internal identifier as the name
 * ("deleni-v-oboru-nasobilky"): shown as words ("Deleni v oboru nasobilky") — the lost accents can't
 * be restored, but it reads as a name, not a code.
 */
export function topicLabel(raw: string | null | undefined): string {
  const s = (raw ?? '').trim()
  const slug = /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(s)
  return displayTitle(slug ? s.replace(/-/g, ' ') : s)
}

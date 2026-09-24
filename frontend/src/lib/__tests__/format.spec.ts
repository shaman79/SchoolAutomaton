import { afterEach, describe, expect, it } from 'vitest'

import { setLocale } from '@/i18n'
import { formatNumber, humanizeSubject, parseNumericAnswer, subjectLabel } from '@/lib/format'

describe('humanizeSubject', () => {
  it('title-cases snake_case keys', () => {
    expect(humanizeSubject('language_arts')).toBe('Language Arts')
  })

  it('handles kebab-case and extra separators', () => {
    expect(humanizeSubject('computer--science')).toBe('Computer Science')
  })

  it('leaves already-human subjects readable', () => {
    expect(humanizeSubject('science')).toBe('Science')
  })

  it('returns empty string for nullish input', () => {
    expect(humanizeSubject(null)).toBe('')
    expect(humanizeSubject(undefined)).toBe('')
    expect(humanizeSubject('')).toBe('')
  })
})

describe('subjectLabel', () => {
  afterEach(() => setLocale('en'))

  it('names known subjects the way a Czech pupil knows them', () => {
    setLocale('cs')
    expect(subjectLabel('math')).toBe('Matematika')
    expect(subjectLabel('language_arts')).toBe('Český jazyk')
    expect(subjectLabel('computer-science')).toBe('Informatika')
  })

  it('uses the English names in English', () => {
    setLocale('en')
    expect(subjectLabel('language_arts')).toBe('Language Arts')
  })

  it('humanizes subjects outside the known list', () => {
    setLocale('cs')
    expect(subjectLabel('astronomy_club')).toBe('Astronomy Club')
    expect(subjectLabel(null)).toBe('')
  })
})

describe('parseNumericAnswer', () => {
  it('reads the Czech decimal comma and space-grouped thousands', () => {
    expect(parseNumericAnswer('3,5', 'cs')).toBe(3.5)
    expect(parseNumericAnswer('12 500', 'cs')).toBe(12500)
    expect(parseNumericAnswer('12 500,25', 'cs')).toBe(12500.25)
    expect(parseNumericAnswer('-0,5', 'cs')).toBe(-0.5)
  })

  it('reads English comma thousands in English, but a lone comma stays decimal', () => {
    expect(parseNumericAnswer('12,500', 'en')).toBe(12500)
    expect(parseNumericAnswer('1,000.5', 'en')).toBe(1000.5)
    expect(parseNumericAnswer('3,5', 'en')).toBe(3.5)
    expect(parseNumericAnswer('12,500', 'cs')).toBe(12.5)
  })

  it('returns null for incomplete or non-numeric input', () => {
    for (const s of ['', ' ', '-', ',', 'abc', '3,5 kg']) expect(parseNumericAnswer(s, 'cs')).toBeNull()
  })
})

describe('formatNumber', () => {
  it('writes numbers the Czech way in Czech', () => {
    expect(formatNumber(3.5, 'cs')).toBe('3,5')
    expect(formatNumber(12500, 'cs').replace(/\s/g, ' ')).toBe('12 500')
    expect(formatNumber(3.5, 'en')).toBe('3.5')
  })
})

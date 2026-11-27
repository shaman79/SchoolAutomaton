import { afterEach, describe, expect, it } from 'vitest'

import { setLocale } from '@/i18n'
import {
  displayTitle,
  formatNumber,
  humanizeSubject,
  parseNumericAnswer,
  subjectLabel,
  topicLabel,
} from '@/lib/format'

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

describe('dayLabel', () => {
  afterEach(() => setLocale('en'))

  it('says today / yesterday, else a short date, in the viewer’s own days', async () => {
    const { dayLabel } = await import('@/lib/format')
    const now = new Date(2026, 10, 25, 9, 0)
    expect(dayLabel(new Date(2026, 10, 25, 0, 5).toISOString(), now)).toBe('today')
    expect(dayLabel(new Date(2026, 10, 24, 23, 55).toISOString(), now)).toBe('yesterday')
    setLocale('cs')
    expect(dayLabel(new Date(2026, 10, 3, 12).toISOString(), now)).toBe('3. 11.')
    expect(dayLabel(new Date(2026, 10, 25, 12).toISOString(), now)).toBe('dnes')
    expect(dayLabel(null, now)).toBe('')
    expect(dayLabel('garbage', now)).toBe('')
  })
})

describe('displayTitle', () => {
  it('drops a bracketed note that only restates the title, and capitalizes it', () => {
    expect(displayTitle('zlomky na obrázcích (vysvětlení zlomků pomocí obrázků)')).toBe(
      'Zlomky na obrázcích',
    )
  })

  it('drops a gloss in another language', () => {
    expect(displayTitle('Vyjmenovaná slova po B (Czech spelling: words after B)')).toBe(
      'Vyjmenovaná slova po B',
    )
  })

  it('keeps a note that adds something', () => {
    expect(displayTitle('Shakespeare (Romeo a Julie)')).toBe('Shakespeare (Romeo a Julie)')
    expect(displayTitle('násobilka (6 a 7)')).toBe('Násobilka (6 a 7)')
    expect(displayTitle('zlomky (sčítání a odčítání)')).toBe('Zlomky (sčítání a odčítání)')
    expect(displayTitle('rovnice (zápis: 2x + 3 = 7)')).toBe('Rovnice (zápis: 2x + 3 = 7)')
  })

  it('leaves words that are not plain lowercase as they are', () => {
    expect(displayTitle('pH roztoků')).toBe('pH roztoků')
    expect(displayTitle('iPhone a baterie')).toBe('iPhone a baterie')
    expect(displayTitle('x na druhou')).toBe('x na druhou')
    expect(displayTitle('Vyjmenovaná slova po B: kvíz')).toBe('Vyjmenovaná slova po B: kvíz')
  })

  it('capitalizes a hyphenated first word and tidies spaces', () => {
    expect(displayTitle('  e-mail  a   dopis ')).toBe('E-mail a dopis')
  })

  it('is empty for nothing', () => {
    expect(displayTitle(null)).toBe('')
    expect(displayTitle('')).toBe('')
  })
})

describe('topicLabel', () => {
  it('shows an identifier left as a name as words', () => {
    expect(topicLabel('deleni-v-oboru-nasobilky')).toBe('Deleni v oboru nasobilky')
    expect(topicLabel('bydlit')).toBe('Bydlit')
  })

  it('keeps real names (and sentences) as written', () => {
    expect(topicLabel('Dělení v oboru násobilky')).toBe('Dělení v oboru násobilky')
    expect(topicLabel('Umím zapsat zlomek z obrázku.')).toBe('Umím zapsat zlomek z obrázku.')
    expect(topicLabel('Vyjmenovaná slova po B (Czech spelling: words after B)')).toBe(
      'Vyjmenovaná slova po B',
    )
  })
})

import { afterEach, describe, expect, it } from 'vitest'

import { czechPluralRule, i18n, setLocale } from '@/i18n'

describe('czechPluralRule', () => {
  it('picks 1 | 2-4 | 0,5+ for three-form messages', () => {
    expect([1, 2, 3, 4, 5, 0, 11, 22].map((n) => czechPluralRule(n, 3))).toEqual([
      0, 1, 1, 1, 2, 2, 2, 2,
    ])
  })

  it('falls back to singular/plural for two-form messages', () => {
    expect(czechPluralRule(1, 2)).toBe(0)
    expect(czechPluralRule(3, 2)).toBe(1)
  })
})

describe('Czech streak copy', () => {
  afterEach(() => setLocale('en'))

  it('declines "den" correctly', () => {
    setLocale('cs')
    const t = i18n.global.t
    expect(t('gamification.streak_count', 1)).toBe('1 den v řadě')
    expect(t('gamification.streak_count', 3)).toBe('3 dny v řadě')
    expect(t('gamification.streak_count', 5)).toBe('5 dní v řadě')
    expect(t('daily.cta_count', { n: 2 }, 2)).toBe('2 otázky čekají na zopakování')
  })

  it('keeps single-form English messages intact', () => {
    setLocale('en')
    expect(i18n.global.t('gamification.streak_count', 3)).toBe('3-day streak')
  })
})

import { describe, expect, it } from 'vitest'

import {
  levelLabel,
  schoolYearGroups,
  schoolYearLabel,
  schoolYearOptions,
} from '@/lib/grades'

describe('schoolYearLabel', () => {
  it('names Czech classes: předškolák, N. třída (ZŠ), N. ročník SŠ', () => {
    expect(schoolYearLabel(0, 'cs-CZ')).toBe('Předškolák')
    expect(schoolYearLabel(4, 'cs-CZ')).toBe('4. třída')
    expect(schoolYearLabel(9, 'cs-CZ')).toBe('9. třída')
    expect(schoolYearLabel(10, 'cs-CZ')).toBe('1. ročník SŠ')
    expect(schoolYearLabel(13, 'cs-CZ')).toBe('4. ročník SŠ')
  })

  it('names US grades and UK years (UK Year N+1 = school year N)', () => {
    expect(schoolYearLabel(0, 'en-US')).toBe('Kindergarten')
    expect(schoolYearLabel(4, 'en-US')).toBe('Grade 4')
    expect(schoolYearLabel(6, 'en-GB')).toBe('Year 7')
    expect(schoolYearLabel(4, null)).toBe('Grade 4') // no system chosen -> US naming
  })
})

describe('schoolYearOptions / schoolYearGroups', () => {
  it('offers the Czech four-year upper-secondary school', () => {
    expect(schoolYearOptions('cs-CZ')).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])
    expect(schoolYearOptions('en-US').at(-1)).toBe(12)
  })

  it.each(['cs-CZ', 'en-GB', 'en-US'])('groups cover every option exactly once (%s)', (loc) => {
    const grouped = schoolYearGroups(loc).flatMap((g) => g.years)
    expect(grouped).toEqual(schoolYearOptions(loc))
  })

  it('splits Czech basic school into its two stages', () => {
    const labels = schoolYearGroups('cs-CZ').map((g) => g.label)
    expect(labels).toEqual(['Mateřská škola', '1. stupeň ZŠ', '2. stupeň ZŠ', 'Střední škola'])
  })
})

describe('levelLabel', () => {
  it('prefers the exact school year over the band', () => {
    expect(levelLabel({ grade_band: 'G3-5', school_year: 4 }, 'cs-CZ')).toBe('4. třída')
  })

  it('falls back to the band, and to nothing for an unknown band', () => {
    expect(levelLabel({ grade_band: 'G9-12' }, 'cs-CZ')).toBe('9. třída a SŠ')
    expect(levelLabel({ grade_band: 'G3-5', school_year: null }, 'en-US')).toBe('Grades 3–5')
    expect(levelLabel({ grade_band: 'unknown' }, 'cs-CZ')).toBe('')
  })
})

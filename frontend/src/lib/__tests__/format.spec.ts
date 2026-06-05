import { describe, expect, it } from 'vitest'

import { humanizeSubject } from '@/lib/format'

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

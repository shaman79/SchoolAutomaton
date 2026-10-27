/**
 * Failures become friendly, localized words — never e.message or the backend's `detail`.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { ApiError, NETWORK_ERROR_STATUS, parseRetryAfter } from '@/lib/apiError'
import { answerErrorKey, errorKind, friendlyErrorKey, isTransient } from '@/lib/errors'
import { withRetry } from '@/lib/retry'

afterEach(() => vi.restoreAllMocks())

const err = (status: number, detail?: unknown, retryAfter: number | null = null) =>
  new ApiError(status, typeof detail === 'string' ? detail : `HTTP ${status}`, undefined, detail, retryAfter)

describe('errorKind', () => {
  it('maps HTTP statuses and network failures to a kind', () => {
    expect(errorKind(err(NETWORK_ERROR_STATUS))).toBe('network')
    expect(errorKind(new TypeError('Failed to fetch'))).toBe('network')
    expect(errorKind(err(502))).toBe('server_busy')
    expect(errorKind(err(500))).toBe('server_busy')
    expect(errorKind(err(429, "You're going a bit fast.", 20))).toBe('slow_down')
    expect(errorKind(err(429, 'Daily request limit reached.', 30_000))).toBe('daily_limit')
    expect(errorKind(err(503, 'daily_budget'))).toBe('daily_limit')
    expect(errorKind(err(413))).toBe('too_long')
    expect(errorKind(err(422, [{ loc: ['body'], msg: 'too long' }]))).toBe('too_long')
    expect(errorKind(err(404))).toBe('not_found')
    expect(errorKind(err(400))).toBe('generic')
    expect(errorKind(new Error('boom'))).toBe('generic')
  })

  it('says "offline" when the device itself has no connection', () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    expect(errorKind(err(NETWORK_ERROR_STATUS))).toBe('offline')
  })
})

describe('friendly messages', () => {
  it('never contains the raw backend text, and exists in both languages', () => {
    const cases = [
      err(NETWORK_ERROR_STATUS),
      err(502),
      err(429, 'You are going a bit fast', 5),
      err(429, 'Daily request limit reached', 40_000),
      err(422, [{ msg: 'x' }]),
      err(404),
      new Error('Internal stack trace'),
    ]
    for (const locale of ['en', 'cs'] as const) {
      for (const e of cases) {
        for (const key of [friendlyErrorKey(e), answerErrorKey(e)]) {
          expect(i18n.global.te(key, locale), `${key} in ${locale}`).toBe(true)
          const text = i18n.global.t(key, {}, { locale })
          expect(text).not.toContain('[object Object]')
          expect(text).not.toMatch(/going a bit fast|Daily request|stack trace/)
        }
      }
    }
  })

  it('lets a screen override the message for one kind', () => {
    expect(friendlyErrorKey(err(404), { not_found: 'resume.not_found' })).toBe('resume.not_found')
    expect(friendlyErrorKey(err(502), { not_found: 'resume.not_found' })).toBe('errors.server_busy')
  })

  it('answer failures: slow down on 429, too long on 413/422, "still here" when offline', () => {
    expect(answerErrorKey(err(429, 'x', 10))).toBe('test.answer_slow_down')
    expect(answerErrorKey(err(422, []))).toBe('errors.answer_too_long')
    expect(answerErrorKey(err(413))).toBe('errors.answer_too_long')
    expect(answerErrorKey(err(NETWORK_ERROR_STATUS))).toBe('test.answer_network')
    expect(answerErrorKey(err(500))).toBe('test.grade_error')
  })
})

describe('isTransient', () => {
  it('retries blips, never client errors', () => {
    expect(isTransient(err(NETWORK_ERROR_STATUS))).toBe(true)
    expect(isTransient(new TypeError('Load failed'))).toBe(true)
    expect(isTransient(err(502))).toBe(true)
    expect(isTransient(err(504))).toBe(true)
    expect(isTransient(err(401))).toBe(false)
    expect(isTransient(err(404))).toBe(false)
    expect(isTransient(err(429, 'x', 5))).toBe(false)
    expect(isTransient(err(503, 'daily_budget'))).toBe(false)
  })
})

describe('parseRetryAfter', () => {
  it('reads seconds or an HTTP date', () => {
    expect(parseRetryAfter('30')).toBe(30)
    expect(parseRetryAfter(null)).toBeNull()
    expect(parseRetryAfter('soon')).toBeNull()
    const inAMinute = new Date(Date.now() + 60_000).toUTCString()
    expect(parseRetryAfter(inAMinute)).toBeGreaterThan(50)
  })
})

describe('withRetry', () => {
  const noSleep = () => Promise.resolve()

  it('retries a transient failure, then succeeds', async () => {
    const fn = vi.fn().mockRejectedValueOnce(err(502)).mockResolvedValueOnce('ok')
    await expect(withRetry(fn, { delays: [1, 1], shouldRetry: isTransient, sleep: noSleep })).resolves.toBe('ok')
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('gives up after the last delay and rethrows', async () => {
    const fn = vi.fn().mockRejectedValue(err(NETWORK_ERROR_STATUS))
    await expect(withRetry(fn, { delays: [1, 1], shouldRetry: isTransient, sleep: noSleep })).rejects.toMatchObject({
      status: NETWORK_ERROR_STATUS,
    })
    expect(fn).toHaveBeenCalledTimes(3)
  })

  it('does not retry a definitive answer', async () => {
    const fn = vi.fn().mockRejectedValue(err(401))
    await expect(withRetry(fn, { delays: [1, 1], shouldRetry: isTransient, sleep: noSleep })).rejects.toMatchObject({
      status: 401,
    })
    expect(fn).toHaveBeenCalledTimes(1)
  })
})

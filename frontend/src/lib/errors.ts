/**
 * Friendly errors — the ONE place that turns a failure into words a child can act on.
 *
 * Views never render `e.message` or the backend's `detail` (English, technical, sometimes a
 * validation list that printed as "[object Object]"). They call `friendlyErrorKey(e)` and render
 * `t(key)`: every message is localized, kind, and says what to do next.
 */
import { ApiError, NETWORK_ERROR_STATUS } from '@/lib/apiError'

export type ErrorKind =
  | 'offline' // the device itself has no connection
  | 'network' // no HTTP answer (server unreachable, connection dropped)
  | 'server_busy' // 5xx — the server or a proxy in front of it is struggling (e.g. mid-deploy)
  | 'slow_down' // 429 — a short per-minute limit; fine again in a moment
  | 'daily_limit' // 429 with a long wait, or 503 "daily_budget" — done for today
  | 'too_long' // 413 / 422 — the text sent was too big
  | 'not_found' // 404
  | 'generic'

/** A 429 whose wait is this long is a daily cap, not "slow down a moment". */
const DAILY_LIMIT_MIN_RETRY_AFTER_S = 15 * 60

function isOffline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false
}

/** True for a failure that never got an HTTP answer (fetch rejected). */
export function isNetworkError(e: unknown): boolean {
  if (e instanceof ApiError) return e.status === NETWORK_ERROR_STATUS
  // A bare fetch() failure (outside lib/api) is a TypeError: "Failed to fetch" / "Load failed".
  return e instanceof TypeError
}

function isDailyLimit(e: ApiError): boolean {
  if (e.status === 503) return e.detail === 'daily_budget'
  if (e.retryAfter != null && e.retryAfter >= DAILY_LIMIT_MIN_RETRY_AFTER_S) return true
  return typeof e.detail === 'string' && /daily/i.test(e.detail)
}

export function errorKind(e: unknown): ErrorKind {
  if (isNetworkError(e)) return isOffline() ? 'offline' : 'network'
  if (!(e instanceof ApiError)) return 'generic'
  if (e.status === 429) return isDailyLimit(e) ? 'daily_limit' : 'slow_down'
  if (e.status === 503 && isDailyLimit(e)) return 'daily_limit'
  if (e.status === 413 || e.status === 422) return 'too_long'
  if (e.status === 404) return 'not_found'
  if (e.status >= 500) return 'server_busy'
  return 'generic'
}

/**
 * A failure worth retrying automatically after a short pause: no answer at all, a timeout, or a
 * 5xx (a deploy restarting the server, a proxy hiccup). Never a 4xx — those won't change by retrying
 * (and a 429 asks us to wait longer than an automatic retry would).
 */
export function isTransient(e: unknown): boolean {
  if (isNetworkError(e)) return true
  return e instanceof ApiError && (e.status === 408 || (e.status >= 500 && !isDailyLimit(e)))
}

/** The i18n key of the friendly message for `e`. `overrides` swaps the key for some kinds (e.g. a
 *  404 on the resume screen means "we couldn't find that code"). */
export function friendlyErrorKey(e: unknown, overrides: Partial<Record<ErrorKind, string>> = {}): string {
  const kind = errorKind(e)
  return overrides[kind] ?? `errors.${kind}`
}

/** Sending an answer failed: the question stays answerable with the child's input in place, so every
 *  message says the answer is still there / to try again (429 → slow down, 413/422 → too long). */
const ANSWER_ERROR_KEYS: Record<ErrorKind, string> = {
  offline: 'test.answer_offline',
  network: 'test.answer_network',
  server_busy: 'test.grade_error',
  slow_down: 'test.answer_slow_down',
  daily_limit: 'errors.daily_limit',
  too_long: 'errors.answer_too_long',
  not_found: 'test.grade_error',
  generic: 'test.grade_error',
}

export function answerErrorKey(e: unknown): string {
  return ANSWER_ERROR_KEYS[errorKind(e)]
}

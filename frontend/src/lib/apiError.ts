/** The error every `lib/api` call rejects with when the backend can't be reached or says no. */

/** `status` 0 = the request never got an HTTP answer (offline, DNS, connection reset, CORS). */
export const NETWORK_ERROR_STATUS = 0

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    /** The backend's raw `detail` (a string, or FastAPI's validation list). For matching machine
     *  codes like "daily_budget" only — NEVER render it to a learner (see lib/errors). */
    public detail?: unknown,
    /** Seconds from the Retry-After header (429/503), when the server sent one. */
    public retryAfter: number | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Retry-After is either delay-seconds or an HTTP date. */
export function parseRetryAfter(value: string | null): number | null {
  if (!value) return null
  const secs = Number(value.trim())
  if (Number.isFinite(secs) && secs >= 0) return secs
  const at = Date.parse(value)
  if (Number.isNaN(at)) return null
  return Math.max(0, Math.round((at - Date.now()) / 1000))
}

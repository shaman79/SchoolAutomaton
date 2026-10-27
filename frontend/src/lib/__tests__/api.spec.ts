/**
 * The API client's failure shapes: a network failure is an ApiError(0), a validation list never
 * becomes "[object Object]", Retry-After is kept, and a dropped SSE stream hands over to polling.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, NETWORK_ERROR_STATUS, api, streamGeneration } from '@/lib/api'

afterEach(() => {
  vi.unstubAllGlobals()
})

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

describe('request errors', () => {
  it('turns "no answer at all" into ApiError status 0', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const e = await api.getMe().catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(NETWORK_ERROR_STATUS)
  })

  it('keeps a validation list as `detail` but never as the message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(422, { detail: [{ loc: ['body'], msg: 'too long' }] })))
    const e = await api.submitAnswer({ questionId: 1, value: 'x', latencyMs: 1, usedHint: false }).catch((x) => x)
    expect(e.status).toBe(422)
    expect(e.message).not.toContain('[object Object]')
    expect(Array.isArray(e.detail)).toBe(true)
  })

  it('reads Retry-After on a 429', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(429, { detail: 'slow down' }, { 'Retry-After': '12' })))
    const e = await api.startGeneration('r1').catch((x) => x)
    expect(e.status).toBe(429)
    expect(e.retryAfter).toBe(12)
  })

  it('survives a non-JSON error page (proxy 502 during a deploy)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502, statusText: 'Bad Gateway' })))
    const e = await api.getMe().catch((x) => x)
    expect(e.status).toBe(502)
    expect(e.message).toBe('Bad Gateway')
  })
})

class FakeEventSource {
  static CLOSED = 2
  static last: FakeEventSource
  readyState = 0
  closed = false
  onerror: (() => void) | null = null
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {}
  constructor(public url: string) {
    FakeEventSource.last = this
  }
  addEventListener(name: string, cb: (ev: MessageEvent) => void) {
    ;(this.listeners[name] ??= []).push(cb)
  }
  emit(name: string, data: unknown) {
    for (const cb of this.listeners[name] ?? []) cb({ data: JSON.stringify(data) } as MessageEvent)
  }
  close() {
    this.closed = true
    this.readyState = 2
  }
}

describe('streamGeneration', () => {
  it('hands over to the caller on a transport error, once, with the stream closed', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const onConnectionLost = vi.fn()
    const onFailed = vi.fn()
    streamGeneration('r1', { onConnectionLost, onFailed })
    const es = FakeEventSource.last
    es.onerror?.() // e.g. still CONNECTING after a drop — would otherwise retry forever
    es.onerror?.()
    expect(es.closed).toBe(true)
    expect(onConnectionLost).toHaveBeenCalledTimes(1)
    expect(onFailed).not.toHaveBeenCalled()
  })

  it('passes the failure code through and ignores anything after the terminal event', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const onFailed = vi.fn()
    const onConnectionLost = vi.fn()
    const onReady = vi.fn()
    streamGeneration('r1', { onFailed, onConnectionLost, onReady })
    const es = FakeEventSource.last
    es.emit('failed', { message: 'Generation failed: RateLimitError(...)', code: 'busy' })
    es.emit('ready', { mode: 'study', lesson_id: 1 })
    es.onerror?.()
    expect(onFailed).toHaveBeenCalledWith({ message: 'Generation failed: RateLimitError(...)', code: 'busy' })
    expect(onReady).not.toHaveBeenCalled()
    expect(onConnectionLost).not.toHaveBeenCalled()
  })
})

/**
 * The loading screen always reaches an end: ready, or an error with a reason and Retry. Never an
 * endless spinner — not when starting fails, not when the server reports a failure, not when the SSE
 * connection drops — and nothing keeps running after the screen is left.
 */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import type { GenerationStreamHandlers } from '@/lib/api'

const sse = vi.hoisted(() => ({
  handlers: null as GenerationStreamHandlers | null,
  close: null as Mock | null,
  opened: 0,
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { startGeneration: vi.fn(), getRequestStatus: vi.fn() },
    streamGeneration: vi.fn((_id: string, h: GenerationStreamHandlers) => {
      sse.handlers = h
      sse.opened += 1
      sse.close = vi.fn()
      return { close: sse.close } as unknown as EventSource
    }),
  }
})

import { ApiError, NETWORK_ERROR_STATUS, api } from '@/lib/api'
import {
  GENERATION_DEADLINE_MS,
  POLL_FAST_MS,
  POLL_MAX_FAILURES,
  POLL_SLOW_MS,
  useGenerationStore,
} from '@/stores/generation'

const mocked = api as unknown as Record<string, Mock>

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  vi.clearAllMocks()
  sse.handlers = null
  sse.opened = 0
  mocked.startGeneration.mockResolvedValue({ request_id: 'R', status: 'queued' })
})
afterEach(() => vi.useRealTimers())

describe('starting', () => {
  it('a rejected start (429) ends in an error with a reason — not "queued" forever', async () => {
    mocked.startGeneration.mockRejectedValue(new ApiError(429, 'You are going a bit fast', undefined, 'x', 20))
    const gen = useGenerationStore()
    await gen.start('R')
    expect(gen.status).toBe('error')
    expect(gen.errorCode).toBe('slow_down')
    expect(sse.opened).toBe(0)
  })

  it('maps the start contract: 503 daily_budget → budget, 404 → not_found, offline → network', async () => {
    const gen = useGenerationStore()
    mocked.startGeneration.mockRejectedValueOnce(new ApiError(503, 'daily_budget', undefined, 'daily_budget'))
    await gen.start('R')
    expect(gen.errorCode).toBe('budget')
    mocked.startGeneration.mockRejectedValueOnce(new ApiError(404, 'Unknown request'))
    await gen.start('R')
    expect(gen.errorCode).toBe('not_found')
    mocked.startGeneration.mockRejectedValueOnce(new ApiError(NETWORK_ERROR_STATUS, 'net'))
    await gen.start('R')
    expect(gen.errorCode).toBe('network')
  })

  it('retrying after an error starts afresh and can succeed', async () => {
    const gen = useGenerationStore()
    mocked.startGeneration.mockRejectedValueOnce(new ApiError(502, 'Bad Gateway'))
    await gen.start('R')
    expect(gen.status).toBe('error')
    await gen.start('R')
    expect(gen.status).toBe('queued')
    expect(gen.errorCode).toBeNull()
    sse.handlers!.onReady!({ mode: 'study', lesson_id: 11 })
    expect(gen.status).toBe('ready')
    expect(gen.lessonId).toBe(11)
    expect(gen.requestId).toBe('R')
  })
})

describe('server-reported failure', () => {
  it('shows the reason from the code, never the server message', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    sse.handlers!.onFailed!({ message: 'RateLimitError: overloaded_error', code: 'busy' })
    expect(gen.status).toBe('error')
    expect(gen.errorCode).toBe('busy')
  })

  it('"ready" with nothing to open is an error, not an endless "almost ready"', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    sse.handlers!.onReady!({ mode: 'study' })
    expect(gen.status).toBe('error')
    expect(gen.errorCode).toBe('failed')
  })

  it('an unknown or missing code is the generic failure', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    sse.handlers!.onFailed!({ message: 'x' })
    expect(gen.errorCode).toBe('failed')
  })
})

describe('when the SSE connection drops', () => {
  it('polls the status and finishes when it is ready', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    mocked.getRequestStatus.mockResolvedValueOnce({ request_id: 'R', status: 'generating', mode: 'test', lesson_id: null, quiz_id: null })
    mocked.getRequestStatus.mockResolvedValueOnce({ request_id: 'R', status: 'ready', mode: 'test', lesson_id: null, quiz_id: 5 })

    sse.handlers!.onConnectionLost!()
    await vi.advanceTimersByTimeAsync(0)
    expect(gen.status).toBe('generating')
    await vi.advanceTimersByTimeAsync(POLL_FAST_MS)
    expect(gen.status).toBe('ready')
    expect(gen.resultMode).toBe('test')
    expect(gen.quizId).toBe(5)
  })

  it('reports the server error code found by polling', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    mocked.getRequestStatus.mockResolvedValue({ request_id: 'R', status: 'error', mode: 'study', lesson_id: null, quiz_id: null, error_code: 'budget' })
    sse.handlers!.onConnectionLost!()
    await vi.advanceTimersByTimeAsync(0)
    expect(gen.status).toBe('error')
    expect(gen.errorCode).toBe('budget')
  })

  it('gives up with "connection lost" after repeated poll failures (with a Retry)', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    mocked.getRequestStatus.mockRejectedValue(new ApiError(NETWORK_ERROR_STATUS, 'net'))
    sse.handlers!.onConnectionLost!()
    await vi.advanceTimersByTimeAsync(2 * 60_000)
    expect(mocked.getRequestStatus).toHaveBeenCalledTimes(POLL_MAX_FAILURES)
    expect(gen.status).toBe('error')
    expect(gen.errorCode).toBe('network')
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mocked.getRequestStatus).toHaveBeenCalledTimes(POLL_MAX_FAILURES) // and stops polling
  })

  it('has a ceiling: far too long without an end → "timeout" error', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    mocked.getRequestStatus.mockResolvedValue({ request_id: 'R', status: 'generating', mode: 'study', lesson_id: null, quiz_id: null })
    sse.handlers!.onConnectionLost!()
    await vi.advanceTimersByTimeAsync(GENERATION_DEADLINE_MS + POLL_FAST_MS)
    expect(gen.status).toBe('error')
    expect(gen.errorCode).toBe('timeout')
  })
})

it('a healthy stream is still checked now and then, so a silently stuck stream ends too', async () => {
  const gen = useGenerationStore()
  await gen.start('R')
  mocked.getRequestStatus.mockResolvedValue({ request_id: 'R', status: 'ready', mode: 'study', lesson_id: 3, quiz_id: null })
  await vi.advanceTimersByTimeAsync(POLL_SLOW_MS)
  expect(gen.status).toBe('ready')
  expect(gen.lessonId).toBe(3)
  expect(sse.close).toHaveBeenCalled()
})

describe('leaving the screen', () => {
  it('stop() closes the stream and stops polling', async () => {
    const gen = useGenerationStore()
    await gen.start('R')
    sse.handlers!.onConnectionLost!()
    gen.stop()
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(mocked.getRequestStatus).not.toHaveBeenCalled()
  })

  it('a start still in flight when the screen is left never opens a stream', async () => {
    let release!: (v: unknown) => void
    mocked.startGeneration.mockReturnValue(new Promise((r) => (release = r)))
    const gen = useGenerationStore()
    const p = gen.start('R')
    gen.stop()
    release({ request_id: 'R', status: 'queued' })
    await p
    expect(sse.opened).toBe(0)
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(mocked.getRequestStatus).not.toHaveBeenCalled()
  })
})

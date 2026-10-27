/**
 * Drives the /loading screen: kicks off generation and follows it until it is ready or has failed.
 *
 * Progress arrives over SSE. The screen must ALWAYS reach an end — never spin forever:
 *  - starting fails (429, 503 daily budget, offline…)  -> error with a reason + Retry
 *  - the server reports `failed` (with a code)          -> error with that reason + Retry
 *  - the SSE connection drops                           -> fall back to polling GET /requests/{id}
 *  - polling keeps failing / it takes far too long      -> error + Retry
 * A slow status poll also runs while the stream is healthy, so a silently stuck stream still ends.
 * `stop()` cancels everything — including a start or poll still in flight — so nothing leaks after
 * the screen is left.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, streamGeneration } from '@/lib/api'
import { ApiError } from '@/lib/apiError'
import { errorKind } from '@/lib/errors'
import type { RequestStatus } from '@/types/session'

export type GenStatus = 'idle' | 'queued' | 'generating' | 'ready' | 'error'

/** Why the loading screen ended in an error — each has its own friendly message (loading.err_*).
 *  The first four come from the server (SSE `failed.code` / `error_code`). */
export type GenErrorCode =
  | 'busy'
  | 'unavailable'
  | 'budget'
  | 'failed'
  | 'slow_down'
  | 'network'
  | 'offline'
  | 'timeout'
  | 'not_found'

const SERVER_CODES: readonly string[] = ['busy', 'unavailable', 'budget', 'failed']

/** Status poll while the SSE stream is healthy (a safety net), and after it dropped. */
export const POLL_SLOW_MS = 15_000
export const POLL_FAST_MS = 3_000
/** Back-off cap for consecutive poll failures, and how many in a row mean "connection lost". */
export const POLL_FAIL_CAP_MS = 10_000
export const POLL_MAX_FAILURES = 6
/** A lesson takes ~30-60 s; far beyond that something is stuck — offer Retry (idempotent). */
export const GENERATION_DEADLINE_MS = 5 * 60_000

interface SectionStub {
  ordinal: number
  kind: string
  title?: string
}

function serverCode(code: unknown): GenErrorCode {
  return typeof code === 'string' && SERVER_CODES.includes(code) ? (code as GenErrorCode) : 'failed'
}

/** POST /requests/{id}/generate failed: map it to a reason (contract: 404, 409, 429, 503 budget). */
function startErrorCode(e: unknown): GenErrorCode {
  const kind = errorKind(e)
  if (kind === 'daily_limit') return 'budget'
  if (kind === 'slow_down') return 'slow_down'
  if (kind === 'offline' || kind === 'network') return kind
  if (kind === 'not_found') return 'not_found'
  if (kind === 'server_busy') return 'busy'
  return 'failed'
}

export const useGenerationStore = defineStore('generation', () => {
  const status = ref<GenStatus>('idle')
  const sections = ref<SectionStub[]>([])
  const resultMode = ref<'study' | 'test' | null>(null)
  const lessonId = ref<number | null>(null)
  const quizId = ref<number | null>(null)
  /** The request these results belong to — views use the ids only for a matching route. */
  const requestId = ref<string | null>(null)
  const errorCode = ref<GenErrorCode | null>(null)

  let es: EventSource | null = null
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let pollFailures = 0
  let deadline = 0
  // Bumped by stop()/reset()/start(): anything still in flight from an older run is ignored.
  let run = 0

  const isTerminal = () => status.value === 'ready' || status.value === 'error'

  function fail(code: GenErrorCode): void {
    _halt()
    status.value = 'error'
    errorCode.value = code
  }

  function succeed(d: { mode?: string | null; lesson_id?: number | null; quiz_id?: number | null }): void {
    // "Ready" with nothing to open would leave the screen on "Almost ready!" forever.
    if (d.lesson_id == null && d.quiz_id == null) {
      fail('failed')
      return
    }
    _halt()
    resultMode.value = d.mode === 'test' || d.mode === 'study' ? d.mode : null
    lessonId.value = d.lesson_id ?? null
    quizId.value = d.quiz_id ?? null
    status.value = 'ready'
  }

  function applyStatus(s: RequestStatus): boolean {
    if (s.status === 'ready') {
      succeed(s)
      return true
    }
    if (s.status === 'error') {
      fail(serverCode(s.error_code))
      return true
    }
    if (s.status === 'generating') status.value = 'generating'
    return false
  }

  function schedulePoll(ms: number, myRun: number): void {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = setTimeout(() => void pollOnce(myRun), ms)
  }

  async function pollOnce(myRun: number): Promise<void> {
    pollTimer = null
    if (myRun !== run || isTerminal() || !requestId.value) return
    if (Date.now() >= deadline) {
      fail('timeout')
      return
    }
    try {
      const s = await api.getRequestStatus(requestId.value)
      if (myRun !== run || isTerminal()) return
      pollFailures = 0
      if (!applyStatus(s)) schedulePoll(es ? POLL_SLOW_MS : POLL_FAST_MS, myRun)
    } catch (e) {
      if (myRun !== run || isTerminal()) return
      if (e instanceof ApiError && e.status === 404) {
        fail('not_found')
        return
      }
      pollFailures += 1
      if (pollFailures >= POLL_MAX_FAILURES) {
        const kind = errorKind(e)
        fail(kind === 'offline' ? 'offline' : kind === 'server_busy' ? 'busy' : 'network')
        return
      }
      schedulePoll(Math.min(POLL_FAST_MS * 2 ** (pollFailures - 1), POLL_FAIL_CAP_MS), myRun)
    }
  }

  function openStream(id: string, myRun: number): void {
    es = streamGeneration(id, {
      onStatus: (d) => {
        if (myRun === run && d.status === 'generating' && !isTerminal()) status.value = 'generating'
      },
      onPlan: (d) => {
        if (myRun !== run) return
        const list = (d as { sections?: SectionStub[] }).sections
        if (Array.isArray(list)) sections.value = list
      },
      onSection: (d) => {
        if (myRun !== run) return
        const i = sections.value.findIndex((s) => s.ordinal === d.ordinal)
        if (i >= 0) sections.value[i] = { ...sections.value[i], ...d }
        else sections.value.push(d)
      },
      onReady: (d) => {
        if (myRun === run) succeed(d)
      },
      // The server's own words (`message`) are never shown — only the code picks the message.
      onFailed: (d) => {
        if (myRun === run) fail(serverCode(d.code))
      },
      // Stream gone: poll the status instead, right away and then every few seconds.
      onConnectionLost: () => {
        if (myRun !== run || isTerminal()) return
        es = null
        schedulePoll(0, myRun)
      },
    })
    schedulePoll(POLL_SLOW_MS, myRun)
  }

  /** Start (or re-join — the endpoint is idempotent) generation for `id` and follow it. Never
   *  rejects: every failure ends in status 'error' with an `errorCode`. */
  async function start(id: string): Promise<void> {
    reset()
    const myRun = run
    requestId.value = id
    status.value = 'queued'
    deadline = Date.now() + GENERATION_DEADLINE_MS
    let started: { status: string }
    try {
      started = await api.startGeneration(id)
    } catch (e) {
      if (myRun === run) fail(startErrorCode(e))
      return
    }
    if (myRun !== run) return // left the screen (or retried) while starting
    if (started.status === 'generating') status.value = 'generating'
    // Even an already-'ready' request goes through the stream: it replays the terminal event with
    // the lesson/quiz ids (and the poll fallback covers a stream that can't connect).
    openStream(id, myRun)
  }

  /** Stop following (screen left). Cancels the stream, polling and anything in flight. */
  function _halt(): void {
    run += 1
    es?.close()
    es = null
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = null
    pollFailures = 0
  }

  function stop(): void {
    _halt()
  }

  function reset(): void {
    _halt()
    status.value = 'idle'
    sections.value = []
    resultMode.value = null
    lessonId.value = null
    quizId.value = null
    requestId.value = null
    errorCode.value = null
  }

  return {
    status,
    sections,
    resultMode,
    lessonId,
    quizId,
    requestId,
    errorCode,
    start,
    stop,
    reset,
  }
})

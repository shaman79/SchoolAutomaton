/**
 * Typed API client — the frontend's single seam to the backend (mirrors `app/api/v1`).
 * Injects the learner `X-Resume-Code` header; admin calls pass a bearer token explicitly.
 */

import type { AnswerEvent, ItemPublic } from '@/types/question'
import { ApiError, NETWORK_ERROR_STATUS, parseRetryAfter } from './apiError'
import type {
  AttemptStart,
  Decision,
  GenerationErrorCode,
  GamificationSnapshot,
  GradeResult,
  LearningSessionSummary,
  Lesson,
  LessonProgress,
  LessonSection,
  ParentSummary,
  ProfileCreateOut,
  ProfileEnvelope,
  ProfileSettings,
  Quiz,
  QuizReview,
  RequestStatus,
} from '@/types/session'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const RESUME_KEY = 'sa_resume_code'

let resumeCode: string | null = localStorage.getItem(RESUME_KEY)

export function setResumeCode(code: string | null): void {
  resumeCode = code
  if (code) localStorage.setItem(RESUME_KEY, code)
  else localStorage.removeItem(RESUME_KEY)
}
export function getResumeCode(): string | null {
  return resumeCode
}

// The error type lives in its own module so the friendly-error mapper (lib/errors) keeps working
// when a test mocks this one.
export { ApiError, NETWORK_ERROR_STATUS, parseRetryAfter } from './apiError'

interface RequestOpts {
  method?: string
  body?: unknown
  bearer?: string
  signal?: AbortSignal
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (resumeCode) headers['X-Resume-Code'] = resumeCode
  if (opts.bearer) headers['Authorization'] = `Bearer ${opts.bearer}`

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    // fetch only rejects when no HTTP answer arrived at all (offline, connection dropped, DNS…).
    throw new ApiError(NETWORK_ERROR_STATUS, 'Network request failed', 'network')
  }

  if (!res.ok) {
    let detail: unknown = undefined
    let code: string | undefined
    try {
      const data = await res.json()
      detail = data?.detail
      if (typeof data?.code === 'string') code = data.code
    } catch {
      /* non-JSON error (e.g. a proxy's HTML 502 page) */
    }
    // `message` is always a plain string (FastAPI's 422 `detail` is a list, which used to surface
    // as "[object Object]"). Views never show it anyway — they map the status via lib/errors.
    const message = typeof detail === 'string' ? detail : res.statusText || `HTTP ${res.status}`
    throw new ApiError(res.status, message, code, detail, parseRetryAfter(res.headers.get('Retry-After')))
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// --------------------------------------------------------------------------- profiles
export const api = {
  createProfile: (body: {
    locale?: string
    education_locale?: string | null
    school_year?: number | null
    age_band?: string
    display_name?: string
  }) => request<ProfileCreateOut>('/profiles', { method: 'POST', body }),

  resumeProfile: (code: string) =>
    request<ProfileEnvelope>('/profiles/resume', { method: 'POST', body: { resume_code: code } }),

  getMe: () => request<ProfileEnvelope>('/profiles/me'),

  updateSettings: (patch: Partial<ProfileSettings> & { display_name?: string }) =>
    request<ProfileSettings>('/profiles/me/settings', { method: 'PATCH', body: patch }),

  getGamification: () => request<GamificationSnapshot>('/profiles/me/gamification'),

  /** Parent overview of the last `days` days (activity + practised topics judged in words). */
  getSummary: (days = 7) => request<ParentSummary>(`/profiles/me/summary?days=${days}`),

  getMyRequests: () => request<LearningSessionSummary[]>('/profiles/me/requests'),

  /** The unfinished lesson/quiz the learner was most recently in (with their position), or null. */
  getContinue: () => request<LearningSessionSummary | null>('/profiles/me/continue'),

  /** Ready lessons/quizzes to revisit or explore next. Seed with `requestId` (a just-finished
   *  session) for "more like this"; omit it on the home screen for the learner's recent sessions. */
  getRecommendations: (params: { requestId?: string; subject?: string; limit?: number } = {}) => {
    const qs = new URLSearchParams()
    if (params.requestId) qs.set('request_id', params.requestId)
    if (params.subject) qs.set('subject', params.subject)
    if (params.limit) qs.set('limit', String(params.limit))
    const q = qs.toString()
    return request<LearningSessionSummary[]>(`/profiles/me/recommendations${q ? `?${q}` : ''}`)
  },

  getTree: (subject?: string) =>
    request<unknown>(`/profiles/me/tree${subject ? `?subject=${encodeURIComponent(subject)}` : ''}`),

  // ------------------------------------------------------------------------- requests / generation
  /** `locale` is the learner's education-system setting (e.g. 'en-GB') — drives the curriculum +
   *  output language of the generated lesson/quiz. `schoolYear` is their class setting, used only
   *  when the prompt itself names no level. */
  submitPrompt: (prompt: string, locale?: string | null, schoolYear?: number | null) =>
    request<Decision>('/requests', {
      method: 'POST',
      body: { prompt, locale, school_year: schoolYear ?? null },
    }),

  /** Idempotent: an already queued/generating/ready request just reports its status. */
  startGeneration: (requestId: string) =>
    request<{ request_id: string; status: 'queued' | 'generating' | 'ready' }>(`/requests/${requestId}/generate`, {
      method: 'POST',
      body: {},
    }),

  getRequestStatus: (requestId: string) => request<RequestStatus>(`/requests/${requestId}`),

  // ------------------------------------------------------------------------- content
  getLesson: (id: number) => request<Lesson>(`/lessons/${id}`),

  /** Progressive generation: build (or fetch, if ready) one lesson section on demand. */
  generateSection: (lessonId: number, ordinal: number) =>
    request<LessonSection>(`/lessons/${lessonId}/sections/${ordinal}/generate`, {
      method: 'POST',
      body: {},
    }),
  /** Fetch one section (incl. current visual statuses) — used to poll pending image placeholders. */
  getSection: (lessonId: number, ordinal: number) =>
    request<LessonSection>(`/lessons/${lessonId}/sections/${ordinal}`),
  /** Report the learner's reveal boundary and get back their saved position + already-graded answers.
   *  Forward-only server-side, so calling it with 0 on open restores without moving anything back. */
  syncLessonProgress: (lessonId: number, revealedUpTo: number) =>
    request<LessonProgress>(`/lessons/${lessonId}/progress`, {
      method: 'PUT',
      body: { revealed_up_to: revealedUpTo },
    }),
  getQuiz: (id: number) => request<Quiz>(`/quizzes/${id}`),

  /** Starts an attempt — or resumes the learner's open one, replaying their position + answers. */
  startAttempt: (quizId: number) =>
    request<AttemptStart>(`/quizzes/${quizId}/attempts`, { method: 'POST', body: {} }),

  /** Remember which question the learner moved to, so the attempt resumes there. */
  saveAttemptPosition: (attemptId: number, currentIndex: number) =>
    request<{ current_index: number }>(`/attempts/${attemptId}/position`, {
      method: 'PUT',
      body: { current_index: currentIndex },
    }),

  submitAnswer: (e: AnswerEvent & { attemptId?: number | null }) =>
    request<GradeResult>('/answers', {
      method: 'POST',
      body: {
        item_id: e.questionId,
        attempt_id: e.attemptId ?? null,
        submitted_value: e.value,
        used_hint: e.usedHint,
        latency_ms: e.latencyMs,
      },
    }),

  completeAttempt: (attemptId: number) =>
    request<unknown>(`/attempts/${attemptId}/complete`, { method: 'POST', body: {} }),

  /** Reveal the learner's most recent attempt at a quiz for review (answers + explanations). */
  getQuizReview: (quizId: number) => request<QuizReview>(`/quizzes/${quizId}/review`),

  // ------------------------------------------------------------------------- review
  getDue: (limit?: number, subject?: string) => {
    const qs = new URLSearchParams()
    if (limit) qs.set('limit', String(limit))
    if (subject) qs.set('subject', subject)
    const q = qs.toString()
    return request<{ items: ItemPublic[]; composition: unknown }>(`/review/due${q ? `?${q}` : ''}`)
  },

  reviewItem: (itemId: number, body: { rating?: number; submitted_value?: unknown; used_hint?: boolean; latency_ms?: number }) =>
    request<GradeResult>(`/review/${itemId}`, { method: 'POST', body }),

  // ------------------------------------------------------------------------- admin
  adminLogin: (username: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in: number }>(
      '/admin/auth/login',
      { method: 'POST', body: { username, password } },
    ),
  adminDashboard: (token: string) => request<unknown>('/admin/dashboard', { bearer: token }),
  adminAudit: (token: string, params: Record<string, string> = {}) =>
    request<unknown>(`/admin/audit?${new URLSearchParams(params).toString()}`, { bearer: token }),
  adminGetSettings: (token: string) => request<unknown>('/admin/settings', { bearer: token }),
  adminPutSetting: (token: string, body: { key: string; value: unknown; is_secret?: boolean }) =>
    request<unknown>('/admin/settings', { method: 'PUT', body, bearer: token }),
  adminContent: (token: string) => request<unknown>('/admin/content', { bearer: token }),
}

// --------------------------------------------------------------------------- SSE generation progress
export interface GenerationStreamHandlers {
  onStatus?: (d: { status: string }) => void
  onPlan?: (d: unknown) => void
  onSection?: (d: { ordinal: number; kind: string; title?: string }) => void
  onReady?: (d: { mode: string; lesson_id?: number | null; quiz_id?: number | null }) => void
  /** Terminal server-side failure (`failed` event). `message` is for logs only — never shown. */
  onFailed?: (d: { message?: string; code?: GenerationErrorCode | string | null }) => void
  /** The stream itself broke (dropped connection, proxy error, server restart). The stream is
   *  already closed when this fires; the caller falls back to polling `GET /requests/{id}`. */
  onConnectionLost?: () => void
}

export function streamGeneration(requestId: string, h: GenerationStreamHandlers): EventSource {
  const es = new EventSource(`${API_BASE}/requests/${requestId}/stream`)
  let closed = false
  const close = () => {
    closed = true
    es.close()
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const on = (name: string, cb?: (d: any) => void) => {
    if (!cb) return
    es.addEventListener(name, (ev: MessageEvent) => {
      if (closed) return
      let data: unknown
      try {
        data = JSON.parse(ev.data)
      } catch {
        return /* ignore malformed frame */
      }
      cb(data)
    })
  }
  on('status', h.onStatus)
  on('plan', h.onPlan)
  on('section', h.onSection)
  on('ready', (d) => {
    close()
    h.onReady?.(d ?? {})
  })
  // Backend terminal failure event is named 'failed' (not 'error') so it doesn't shadow the native
  // EventSource 'error' event that fires on transport drops.
  on('failed', (d) => {
    close()
    h.onFailed?.(d ?? {})
  })
  // Native transport error. EventSource would quietly keep reconnecting (forever on some phones), so
  // hand over to the caller's status polling instead — it is cheap and always reaches an end.
  es.onerror = () => {
    if (closed) return
    close()
    h.onConnectionLost?.()
  }
  return es
}

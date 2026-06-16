/**
 * Typed API client — the frontend's single seam to the backend (mirrors `app/api/v1`).
 * Injects the learner `X-Resume-Code` header; admin calls pass a bearer token explicitly.
 */

import type { AnswerEvent, ItemPublic } from '@/types/question'
import type {
  Decision,
  GamificationSnapshot,
  GradeResult,
  LearningSessionSummary,
  Lesson,
  LessonSection,
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

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

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

  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  })

  if (!res.ok) {
    let detail = res.statusText
    let code: string | undefined
    try {
      const data = await res.json()
      detail = data.detail ?? detail
      code = data.code
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail, code)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// --------------------------------------------------------------------------- profiles
export const api = {
  createProfile: (body: {
    locale?: string
    education_locale?: string | null
    age_band?: string
    display_name?: string
  }) => request<ProfileCreateOut>('/profiles', { method: 'POST', body }),

  resumeProfile: (code: string) =>
    request<ProfileEnvelope>('/profiles/resume', { method: 'POST', body: { resume_code: code } }),

  getMe: () => request<ProfileEnvelope>('/profiles/me'),

  updateSettings: (patch: Partial<ProfileSettings> & { display_name?: string }) =>
    request<ProfileSettings>('/profiles/me/settings', { method: 'PATCH', body: patch }),

  getGamification: () => request<GamificationSnapshot>('/profiles/me/gamification'),

  getMyRequests: () => request<LearningSessionSummary[]>('/profiles/me/requests'),

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
   *  output language of the generated lesson/quiz. */
  submitPrompt: (prompt: string, locale?: string | null) =>
    request<Decision>('/requests', { method: 'POST', body: { prompt, locale } }),

  startGeneration: (requestId: string) =>
    request<{ request_id: string; status: string }>(`/requests/${requestId}/generate`, {
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
  getQuiz: (id: number) => request<Quiz>(`/quizzes/${id}`),

  startAttempt: (quizId: number) =>
    request<{ attempt_id: number; started_at: string }>(`/quizzes/${quizId}/attempts`, {
      method: 'POST',
      body: {},
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
  onReady?: (d: { mode: string; lesson_id?: number; quiz_id?: number }) => void
  onError?: (d: { message: string }) => void
}

export function streamGeneration(requestId: string, h: GenerationStreamHandlers): EventSource {
  const es = new EventSource(`${API_BASE}/requests/${requestId}/stream`)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const on = (name: string, cb?: (d: any) => void) => {
    if (!cb) return
    es.addEventListener(name, (ev: MessageEvent) => {
      try {
        cb(JSON.parse(ev.data))
      } catch {
        /* ignore malformed frame */
      }
    })
  }
  on('status', h.onStatus)
  on('plan', h.onPlan)
  on('section', h.onSection)
  on('ready', (d) => {
    h.onReady?.(d)
    es.close()
  })
  // Backend terminal failure event is named 'failed' (not 'error') so it doesn't shadow the native
  // EventSource 'error' event that fires on transport drops.
  on('failed', (d) => {
    h.onError?.(d)
    es.close()
  })
  // Native transport error (connection drop / server gone). EventSource auto-reconnects while the
  // readyState is CONNECTING; only surface a hard failure once it's CLOSED.
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      h.onError?.({ message: 'Connection lost. Please try again.' })
    }
  }
  return es
}

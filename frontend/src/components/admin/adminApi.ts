/**
 * F5 Admin — local response types + helpers.
 *
 * The frozen typed client (`src/lib/api.ts`) returns `unknown` for the admin endpoints
 * (the OpenAPI-generated `src/types/api.ts` is owned by the spine). These interfaces mirror
 * the backend Pydantic schemas in `backend/app/schemas/admin.py` so the admin console is typed
 * without modifying frozen contracts. Keep them in sync with that file.
 */
import { ApiError } from '@/lib/api'

/** GET /admin/dashboard → DashboardOut */
export interface DashboardOut {
  requests_24h: number
  decisions_breakdown: Record<string, number>
  anthropic_cost_usd: number
  replicate_cost_usd: number
  cache_hit_rate: number
  crisis_events: number
  refusals: number
  injection_attempts: number
  profiles_total: number
  lessons_total: number
  quizzes_total: number
}

/** One row of GET /admin/audit (paginated) → AuditRecord */
export interface AuditRecord {
  id: number
  request_id: string
  ts: string
  decision_type: string
  language: string | null
  suspicion_score: number
  injection_detected: boolean
  safety_flags: string[] | null
  reason: string | null
  raw_length: number
  /** topic is stored HASHED — never the student's words */
  topic_hash: string | null
}

/** GET /admin/audit → Page[AuditRecord] */
export interface AuditPage {
  items: AuditRecord[]
  total: number
  page: number
  page_size: number
}

/** GET/PUT /admin/settings → SettingItem; secrets come back as the string '***'. */
export interface SettingItem {
  key: string
  value: unknown | null
  is_secret: boolean
  updated_at: string | null
}

/** GET /admin/content → ContentRecord[] */
export interface ContentRecord {
  id: number
  kind: string // 'lesson' | 'quiz'
  topic: string
  grade_band: string
  language: string
  cache_key: string | null
  created_at: string
}

/** Decision types known to the sanitizer (SPEC §3). */
export const DECISION_TYPES = ['proceed', 'clarify', 'refuse', 'crisis'] as const

/** True when an error is an expired/invalid admin session (→ redirect to login). */
export function isUnauthorized(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 401 || e.status === 403)
}

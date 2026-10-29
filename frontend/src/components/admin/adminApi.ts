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

/** A setting's value: kind 'status' (API keys) is a boolean "is set" — the key itself is never sent. */
export type ConfigValue = string | number | boolean | null
/** default = the app's own default; env = the server's environment / .env (`env_name`);
 *  admin = changed on the Settings page; code = fixed in this release. */
export type ConfigSource = 'default' | 'env' | 'admin' | 'code'
export type ConfigKind = 'choice' | 'number' | 'integer' | 'text' | 'status'
export type ConfigGroup = 'models' | 'spending' | 'limits' | 'keys' | 'about'

/** One setting as the backend runs it now (GET /admin/config items; PUT/DELETE /admin/config/{key}). */
export interface ConfigItem {
  key: string
  /** Typed as the known groups, but render an unknown one too (a newer backend may add groups). */
  group: ConfigGroup | (string & {})
  kind: ConfigKind | (string & {})
  /** In effect NOW. */
  value: ConfigValue
  source: ConfigSource
  env_name: string | null
  /** The setting can be changed on the Settings page (by a role that may edit — see `can_edit`). */
  editable: boolean
  /** What applies without the admin change — what "undo" returns to. */
  base_value: ConfigValue
  base_source: ConfigSource | null
  /** The app's own default = the recommended choice. */
  default_value: ConfigValue
  /** For kind 'choice'. */
  choices: string[]
  min: number | null
  max: number | null
  /** ISO; set when source === 'admin'. */
  updated_at: string | null
  /** Admin username; set when source === 'admin'. */
  updated_by: string | null
}

/** AI calls since 00:00 UTC for one provider/model. */
export interface ModelUsageToday {
  provider: string
  model: string
  calls: number
  /** null = the model has no known price. */
  cost_usd: number | null
  last_call_at: string | null
}

/** GET /admin/config → AdminConfigOut */
export interface AdminConfigOut {
  /** false for a read-only ("viewer") admin. */
  can_edit: boolean
  /** In display order. */
  items: ConfigItem[]
  /** Sorted by cost, highest first. */
  usage_today: ModelUsageToday[]
  spent_today_usd: number
  /** 0 = no daily cap. */
  budget_usd: number
  /** ISO, 00:00 UTC today — "today" for the budget and the usage list. */
  day_started_at: string
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

/** Hand-written types for what the stores/UI use. Full API surface: `src/types/api.ts` (generated). */

import type { ItemPublic } from './question'

export type DecisionType = 'proceed' | 'clarify' | 'refuse' | 'crisis'
export type Mode = 'study' | 'test'

export interface StructuredIntent {
  subject: string
  topic: string
  mode: Mode
  grade_band: string
  age: number | null
  age_band: string
  language: string
  constraints: string[]
  is_educational: boolean
  off_task: boolean
  safety_flags: string[]
  injection_detected: boolean
  classifier_confidence: number
}

export interface CrisisResource {
  name: string
  phone?: string | null
  sms?: string | null
  url?: string | null
  country: string
  hours?: string | null
}

export type Decision =
  | { type: 'proceed'; request_id: string; mode: Mode; intent: StructuredIntent }
  | { type: 'clarify'; request_id: string; question: string; suggestions: string[] }
  | { type: 'refuse'; request_id: string; reason: string; redirect_suggestions: string[] }
  | {
      type: 'crisis'
      request_id: string
      message: string
      resources: CrisisResource[]
      disclosure: string
    }

export interface ProfileSettings {
  theme: string
  font: string
  font_scale: number
  reduced_motion: boolean
  sound: boolean
  locale: string
  daily_goal: 'casual' | 'regular' | 'serious' | 'intense'
  interleave_strength: number
  rest_days_per_week: number
  desired_retention: number
}

export interface ProfilePublic {
  id: number
  display_name: string | null
  total_xp: number
  level: number
  age_band: string
  primary_language: string
  created_at: string | null
}

export interface StreakInfo {
  current: number
  longest: number
  freeze_inventory: number
  is_perfect: boolean
  frozen: boolean
}

export interface BadgeInfo {
  code: string
  title: string
  description: string | null
  tier: number
  unlocked_at: string | null
  progress_numerator: number
  progress_denominator: number
  icon_url: string | null
}

export interface GamificationSnapshot {
  level: number
  total_xp: number
  xp_to_next: number
  level_progress_pct: number
  streak: StreakInfo
  daily_goal: string
  daily_progress_xp: number
  badges: BadgeInfo[]
}

export interface ProfileEnvelope {
  profile: ProfilePublic
  settings: ProfileSettings
  gamification: GamificationSnapshot
}

export interface ProfileCreateOut {
  resume_code: string
  profile: ProfilePublic
  settings: ProfileSettings
}

export interface RequestStatus {
  request_id: string
  status: 'queued' | 'generating' | 'ready' | 'error'
  mode: Mode | null
  lesson_id: number | null
  quiz_id: number | null
}

export interface LearningSessionSummary {
  request_id: string
  mode: Mode
  status: 'queued' | 'generating' | 'ready' | 'error'
  lesson_id: number | null
  quiz_id: number | null
  title: string | null
  subject: string | null
  created_at: string | null
}

export interface FeedbackBlock {
  text: string
  encouragement_focus: 'effort' | 'strategy' | 'progress'
}

export interface GradeResult {
  is_correct: boolean
  partial_credit: number
  correct_answer: unknown
  fsrs_rating: number
  next_due: string | null
  explanation: string | null
  misconception: { description: string; refutation: string } | null
  feedback: FeedbackBlock
  xp_awarded: number
  combo_multiplier: number
  mastery_delta: number
  new_badges: { code: string; title: string; tier: number }[]
  level_up: { from_level: number; to_level: number } | null
}

// ----- lesson delivery -----
export interface AssetRef {
  hash: string
  url: string
  asset_type: string
  layout_slot: string
  alt_text: string
  caption: string | null
  svg_inline: string | null
  label_overlay: unknown[] | null
}
export interface LessonObjective {
  text: string
  bloom_tier: number
  concept_id: number | null
}
export interface LessonSection {
  ordinal: number
  kind: string
  title: string | null
  body_markdown: string | null
  gated: boolean
  assets: AssetRef[]
  items: ItemPublic[]
}
export interface Lesson {
  id: number
  request_id: string
  topic: string
  language: string
  grade_band: string
  subject: string
  objectives: LessonObjective[]
  measured_fkgl: number | null
  lexile_band: string | null
  estimated_duration_min: number | null
  sections: LessonSection[]
}

// ----- quiz delivery -----
export interface QuizQuestion {
  question_id: number
  ordinal: number
  points: number
  item: ItemPublic
}
export interface Quiz {
  id: number
  request_id: string
  title: string
  language: string
  grade_band: string
  subject: string
  quiz_type: string
  questions: QuizQuestion[]
}

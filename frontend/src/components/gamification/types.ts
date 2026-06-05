/**
 * Local view-model types for the F4 gamification UI.
 *
 * These mirror two backend responses that the frozen `api.ts` deliberately types as `unknown`
 * (GET /profiles/me/tree and POST /attempts/{id}/complete), so F4 narrows them HERE rather than
 * touching the frozen contract. The cross-stack source of truth is docs/architecture-design.json
 * (the `/profiles/me/tree` and ResultsSummary response shapes). The fully-typed `GamificationSnapshot`,
 * `StreakInfo`, `BadgeInfo` and `GradeResult` come from `@/types/session` (frozen) — re-exported for
 * convenience so component imports stay short.
 */
export type { BadgeInfo, GamificationSnapshot, GradeResult, StreakInfo } from '@/types/session'

/** Concept node state (matches skill_mastery.node_state in the backend). */
export type NodeState = 'locked' | 'available' | 'learning' | 'mastered' | 'needs_review'

export interface TreeNode {
  concept_id: number
  title: string
  subject: string
  mastery: number // 0..1
  state: NodeState
  prereq_ids: number[]
  related_ids: number[]
  last_reviewed: string | null
  decay_due_at: string | null
}

export interface TreeEdge {
  from_id: number
  to_id: number
  type: string // 'prerequisite' | 'related'
}

export interface KnowledgeTreeData {
  nodes: TreeNode[]
  edges: TreeEdge[]
}

/** One concept whose mastery changed during a finished attempt. */
export interface MasteryChange {
  concept_id: number
  name: string
  before: number
  after: number
  state: NodeState
}

/** POST /attempts/{id}/complete → ResultsSummary. */
export interface ResultsSummary {
  score: number
  max_score: number
  accuracy: number // 0..1
  xp_awarded: number
  combo_max: number
  new_badges: { code: string; title: string; tier: number }[]
  streak: { current: number; longest: number; frozen?: boolean }
  mastery_changes: MasteryChange[]
}

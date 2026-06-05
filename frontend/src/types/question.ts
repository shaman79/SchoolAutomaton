/**
 * Cross-stack question contract — MIRRORS backend `app/schemas/questions.py` (public, no correctness).
 * The discriminator is `payload.kind`. Keep in sync; the backend is the source of truth and
 * `npm run gen:api` regenerates `api.ts` for the full surface.
 */

export type ItemType =
  | 'mcq'
  | 'true_false'
  | 'cloze'
  | 'short_answer'
  | 'numeric'
  | 'match'
  | 'order'
  | 'hotspot'

export interface McqOption {
  id: string
  text: string
}
export interface McqPayload {
  kind: 'mcq'
  options: McqOption[]
  multiple: boolean
}
export interface TrueFalsePayload {
  kind: 'true_false'
  statement: string | null
}
export interface ClozeBlank {
  id: string
  choices: string[] | null // present => drag/select; absent => type-in
}
export interface ClozePayload {
  kind: 'cloze'
  text_template: string // uses {{blank_id}} markers
  blanks: ClozeBlank[]
}
export interface ShortAnswerPayload {
  kind: 'short_answer'
  placeholder: string | null
}
export interface NumericPayload {
  kind: 'numeric'
  unit: string | null
}
export interface MatchSide {
  id: string
  text: string
}
export interface MatchPayload {
  kind: 'match'
  left: MatchSide[]
  right: MatchSide[] // shuffled
}
export interface OrderToken {
  id: string
  text: string
}
export interface OrderPayload {
  kind: 'order'
  tokens: OrderToken[] // shuffled
}
export interface HotspotRegion {
  id: string
  shape: 'rect' | 'circle' | 'poly'
  coords: number[] // normalized 0..1
  label: string | null
}
export interface HotspotPayload {
  kind: 'hotspot'
  image_url: string | null
  image_asset_hash: string | null
  regions: HotspotRegion[]
}

export type QuestionPayload =
  | McqPayload
  | TrueFalsePayload
  | ClozePayload
  | ShortAnswerPayload
  | NumericPayload
  | MatchPayload
  | OrderPayload
  | HotspotPayload

export interface ItemPublic {
  id: number
  item_type: ItemType
  bloom_tier: number
  points: number
  stem_markdown: string
  payload: QuestionPayload
  hint_available: boolean
}

/**
 * Per-type submitted value (the `value` of an AnswerEvent), mirrors backend ANSWER_VALUE_DOC:
 *  mcq: string | string[] (option id(s));  true_false: boolean;  cloze: Record<blankId,string>;
 *  short_answer: string;  numeric: number;  match: {left_id,right_id}[];
 *  order: string[] (token ids);  hotspot: string (region id).
 */
export type SubmittedValue =
  | string
  | string[]
  | boolean
  | number
  | Record<string, string>
  | { left_id: string; right_id: string }[]
  | null

/** Normalized event every question component emits up to the test/lesson store. */
export interface AnswerEvent {
  questionId: number
  value: SubmittedValue
  latencyMs: number
  usedHint: boolean
}

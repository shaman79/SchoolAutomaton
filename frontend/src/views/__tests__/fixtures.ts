/** Shared fixtures for the view tests (not a test file itself). */
import { vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { toast, toasts } from '@/components/common/useToasts'
import type { ItemPublic } from '@/types/question'
import type { AnswerSupport, GradeResult, Lesson, Quiz } from '@/types/session'

/** jsdom lacks matchMedia / scrollTo, which the reduced-motion + reader code use. */
export function stubDom(): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo
}

export function clearToasts(): void {
  for (const t of [...toasts.items]) toast.dismiss(t.id)
}
export function toastTexts(): string[] {
  return toasts.items.map((t) => t.message)
}

export function makeRouter() {
  const blank = { template: '<div />' }
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: blank },
      { path: '/stats', name: 'stats', component: blank },
      { path: '/history', name: 'history', component: blank },
      { path: '/lesson/:sessionId', name: 'lesson', component: blank },
      { path: '/test/:sessionId', name: 'test', component: blank },
      { path: '/results/:sessionId', name: 'results', component: blank },
      { path: '/resume', name: 'resume', component: blank },
    ],
  })
}

export function grade(is_correct: boolean, extra: Partial<GradeResult> = {}): GradeResult {
  return {
    is_correct,
    partial_credit: is_correct ? 1 : 0,
    correct_answer: 'a',
    fsrs_rating: is_correct ? 3 : 1,
    next_due: null,
    explanation: null,
    misconception: null,
    feedback: { text: is_correct ? 'Nice!' : 'Not quite.', encouragement_focus: 'strategy' },
    xp_awarded: 0,
    combo_multiplier: 1,
    mastery_delta: 0,
    new_badges: [],
    level_up: null,
    ...extra,
  }
}

export const SUPPORT: AnswerSupport = {
  message: 'It sounds like things are really hard right now.',
  resources: [{ name: 'Linka bezpečí', phone: '116 111', country: 'CZ' }],
  disclosure: 'I am an AI, not a counsellor.',
}

/** A graded-looking result that actually carries the crisis net (NOT graded, NOT recorded). */
export function supportResult(): GradeResult {
  return { ...grade(false, { correct_answer: null }), support: SUPPORT }
}

export function shortItem(id: number): ItemPublic {
  return {
    id,
    item_type: 'short_answer',
    bloom_tier: 2,
    points: 10,
    stem_markdown: `Question ${id}`,
    hint_available: false,
    payload: { kind: 'short_answer', placeholder: null },
  }
}

export function lesson(id: number, requestId: string, topic: string): Lesson {
  return {
    id,
    request_id: requestId,
    topic,
    language: 'en',
    grade_band: 'G3-5',
    subject: 'science',
    objectives: [],
    measured_fkgl: null,
    lexile_band: null,
    estimated_duration_min: null,
    sections: [
      { ordinal: 0, kind: 'practice', title: 'Try it', body_markdown: 'Text', gated: false, gen_status: 'ready', assets: [], items: [shortItem(id * 10 + 1)] },
    ],
  }
}

export function quiz(id: number, requestId: string, title: string): Quiz {
  return {
    id,
    request_id: requestId,
    title,
    language: 'en',
    grade_band: 'G3-5',
    subject: 'science',
    quiz_type: 'standard',
    questions: [
      { question_id: 1, ordinal: 1, points: 10, item: shortItem(id * 10 + 1) },
      { question_id: 2, ordinal: 2, points: 10, item: shortItem(id * 10 + 2) },
    ],
  }
}

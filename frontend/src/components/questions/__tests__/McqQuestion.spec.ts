import { mount } from '@vue/test-utils'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'

import McqQuestion from '@/components/questions/McqQuestion.vue'
import type { ItemPublic } from '@/types/question'

// jsdom has no matchMedia; the frozen useReducedMotion composable reads it. Stub once.
beforeAll(() => {
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
  }
})

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  messages: {
    en: {
      common: { check: 'Check', correct: 'Correct!', not_yet: 'Not yet — keep going!' },
      feedback: { partial: 'Partly there' },
      q: { mcq: { select_one: 'Select one', select_all: 'Select all that apply' } },
    },
  },
})

function makeItem(multiple: boolean): ItemPublic {
  return {
    id: 42,
    item_type: 'mcq',
    bloom_tier: 2,
    points: 1,
    stem_markdown: 'What is **2 + 2**?',
    hint_available: false,
    payload: {
      kind: 'mcq',
      multiple,
      options: [
        { id: 'a', text: '3' },
        { id: 'b', text: '4' },
        { id: 'c', text: '5' },
      ],
    },
  }
}

function factory(item: ItemPublic, extra: Record<string, unknown> = {}) {
  return mount(McqQuestion, {
    props: { item, ...extra },
    global: { plugins: [i18n] },
  })
}

describe('McqQuestion', () => {
  it('renders the sanitized stem and all options', () => {
    const w = factory(makeItem(false))
    expect(w.html()).toContain('<strong>2 + 2</strong>') // markdown rendered + sanitized
    expect(w.findAll('.sa-option')).toHaveLength(3)
    expect(w.findAll('input[type="radio"]')).toHaveLength(3)
  })

  it('disables Check until a selection is made', async () => {
    const w = factory(makeItem(false))
    const check = w.find('.sa-q__check')
    expect((check.element as HTMLButtonElement).disabled).toBe(true)
    await w.findAll('input')[1].setValue(true)
    expect((check.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('emits a single-select AnswerEvent with the chosen option id', async () => {
    const w = factory(makeItem(false))
    await w.findAll('input')[1].setValue(true)
    await w.find('.sa-q__check').trigger('click')
    const events = w.emitted('answer')
    expect(events).toBeTruthy()
    const payload = events![0][0] as {
      questionId: number
      value: unknown
      usedHint: boolean
      latencyMs: number
    }
    expect(payload.questionId).toBe(42)
    expect(payload.value).toBe('b')
    expect(payload.usedHint).toBe(false)
    expect(typeof payload.latencyMs).toBe('number')
  })

  it('emits an array value when multiple-select', async () => {
    const w = factory(makeItem(true))
    expect(w.findAll('input[type="checkbox"]')).toHaveLength(3)
    await w.findAll('input')[0].trigger('change')
    await w.findAll('input')[2].trigger('change')
    await w.find('.sa-q__check').trigger('click')
    const payload = w.emitted('answer')![0][0] as { value: string[] }
    expect(Array.isArray(payload.value)).toBe(true)
    expect(payload.value).toEqual(['a', 'c'])
  })

  it('shows accessible feedback (role=status) and locks input when feedback is present', () => {
    const w = factory(makeItem(false), {
      feedback: {
        is_correct: true,
        partial_credit: 1,
        correct_answer: 'b',
        fsrs_rating: 3,
        next_due: null,
        explanation: null,
        misconception: null,
        feedback: { text: 'Correct!', encouragement_focus: 'strategy' },
        xp_awarded: 10,
        combo_multiplier: 1,
        mastery_delta: 0.1,
        new_badges: [],
        level_up: null,
      },
    })
    const status = w.find('[role="status"]')
    expect(status.exists()).toBe(true)
    expect(status.attributes('aria-live')).toBe('polite')
    // never color-only: an icon glyph accompanies the text
    expect(status.find('.sa-feedback__icon').exists()).toBe(true)
    expect((w.find('.sa-q__check').element as HTMLButtonElement).disabled).toBe(true)
  })
})

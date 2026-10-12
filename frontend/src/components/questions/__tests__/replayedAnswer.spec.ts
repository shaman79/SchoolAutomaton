/**
 * Resuming a lesson/quiz replays the learner's already-graded answers. Every question type must then
 * show WHAT they answered (the `submitted` prop), not just the verdict — and must show nothing when
 * there is no replayed answer.
 */
import { mount } from '@vue/test-utils'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'

import QuestionRenderer from '@/components/questions/QuestionRenderer.vue'
import TrueFalseQuestion from '@/components/questions/TrueFalseQuestion.vue'
import en from '@/locales/en.json'
import type { ItemPublic, QuestionPayload } from '@/types/question'
import type { GradeResult } from '@/types/session'

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

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const graded: GradeResult = {
  is_correct: false,
  partial_credit: 0,
  correct_answer: null,
  fsrs_rating: 1,
  next_due: null,
  explanation: 'Because.',
  misconception: null,
  feedback: { text: 'Not yet.', encouragement_focus: 'strategy' },
  xp_awarded: 0,
  combo_multiplier: 1,
  mastery_delta: 0,
  new_badges: [],
  level_up: null,
}

function item(payload: QuestionPayload): ItemPublic {
  return {
    id: 7,
    item_type: payload.kind,
    bloom_tier: 2,
    points: 10,
    stem_markdown: 'Question?',
    hint_available: false,
    payload,
  }
}

/** Mount a question the way the reader/runner does after a resume: graded, with the replayed answer. */
function resumed(payload: QuestionPayload, submitted: unknown) {
  return mount(QuestionRenderer, {
    props: { item: item(payload), feedback: graded, disabled: true, submitted },
    global: { plugins: [i18n] },
  })
}

const MCQ: QuestionPayload = {
  kind: 'mcq',
  multiple: false,
  options: [
    { id: 'a', text: 'Apple' },
    { id: 'b', text: 'Banana' },
    { id: 'c', text: 'Cherry' },
  ],
}

describe('a replayed answer is shown as the learner’s answer', () => {
  it('mcq: re-selects the chosen option', () => {
    const w = resumed(MCQ, 'b')
    const checked = w.findAll('input').map((i) => (i.element as HTMLInputElement).checked)
    expect(checked).toEqual([false, true, false])
    expect(w.findAll('.sa-option--checked')).toHaveLength(1)
    expect(w.find('[role="status"]').exists()).toBe(true) // with its feedback
  })

  it('mcq (multi-select): re-selects every chosen option', () => {
    const w = resumed({ ...MCQ, multiple: true }, ['a', 'c'])
    const checked = w.findAll('input').map((i) => (i.element as HTMLInputElement).checked)
    expect(checked).toEqual([true, false, true])
  })

  it('true/false: re-presses the chosen side — including an answer of False', () => {
    const w = resumed({ kind: 'true_false', statement: 'The sky is green.' }, false)
    const pressed = w.findAll('.sa-tf__btn').map((b) => b.attributes('aria-pressed'))
    expect(pressed).toEqual(['false', 'true']) // [True, False] buttons
  })

  it('cloze: refills each blank (typed and chosen)', () => {
    const w = resumed(
      {
        kind: 'cloze',
        text_template: 'Plants use {{b1}} to make {{b2}}.',
        blanks: [
          { id: 'b1', choices: null },
          { id: 'b2', choices: ['sugar', 'salt'] },
        ],
      },
      { b1: 'sunlight', b2: 'sugar' },
    )
    expect((w.find('input.sa-cloze__input').element as HTMLInputElement).value).toBe('sunlight')
    expect((w.find('select.sa-cloze__select').element as HTMLSelectElement).value).toBe('sugar')
  })

  it('short answer: refills the text', () => {
    const w = resumed({ kind: 'short_answer', placeholder: null }, 'chlorophyll')
    expect((w.find('input.sa-sa__input').element as HTMLInputElement).value).toBe('chlorophyll')
  })

  it('numeric: refills the number — including 0', () => {
    const payload: QuestionPayload = { kind: 'numeric', unit: 'cm' }
    expect((resumed(payload, 3.5).find('input').element as HTMLInputElement).value).toBe('3.5')
    expect((resumed(payload, 0).find('input').element as HTMLInputElement).value).toBe('0')
  })

  it('match: puts the paired tokens back in their slots', () => {
    const w = resumed(
      {
        kind: 'match',
        left: [
          { id: 'l1', text: 'Sun' },
          { id: 'l2', text: 'Moon' },
        ],
        right: [
          { id: 'r1', text: 'Night' },
          { id: 'r2', text: 'Day' },
        ],
      },
      [
        { left_id: 'l1', right_id: 'r2' },
        { left_id: 'l2', right_id: 'r1' },
      ],
    )
    expect(w.findAll('.sa-match__token--placed').map((n) => n.text())).toEqual(['Day', 'Night'])
    expect(w.findAll('.sa-match__pool button')).toHaveLength(0) // nothing left unplaced
  })

  it('order: lists the tokens in the order the learner left them', () => {
    const w = resumed(
      {
        kind: 'order',
        tokens: [
          { id: 't1', text: 'Seed' },
          { id: 't2', text: 'Sprout' },
          { id: 't3', text: 'Flower' },
        ],
      },
      ['t3', 't1', 't2'],
    )
    expect(w.findAll('.sa-order__text').map((n) => n.text())).toEqual(['Flower', 'Seed', 'Sprout'])
  })

  it('hotspot: re-selects the chosen region', () => {
    const w = resumed(
      {
        kind: 'hotspot',
        image_url: null,
        image_asset_hash: null,
        regions: [
          { id: 'r1', shape: 'rect', coords: [0, 0, 0.5, 0.5], label: 'Leaf' },
          { id: 'r2', shape: 'rect', coords: [0.5, 0.5, 0.5, 0.5], label: 'Root' },
        ],
      },
      'r2',
    )
    const pressed = w.findAll('.sa-hotspot__region').map((b) => b.attributes('aria-pressed'))
    expect(pressed).toEqual(['false', 'true'])
  })
})

describe('a replayed answer that arrives after the question is on screen', () => {
  it('fills in once the resume state loads', async () => {
    const w = mount(QuestionRenderer, {
      props: { item: item(MCQ) },
      global: { plugins: [i18n] },
    })
    expect(w.findAll('.sa-option--checked')).toHaveLength(0)
    await w.setProps({ feedback: graded, disabled: true, submitted: 'c' })
    const checked = w.findAll('input').map((i) => (i.element as HTMLInputElement).checked)
    expect(checked).toEqual([false, false, true])
  })
})

describe('with no replayed answer, nothing is pre-selected', () => {
  it('true/false stays unanswered (an absent answer must not read as False)', () => {
    // Mounted directly, so the prop is genuinely absent (Vue casts an absent boolean prop to false).
    const w = mount(TrueFalseQuestion, {
      props: { item: item({ kind: 'true_false', statement: 'The sky is green.' }) },
      global: { plugins: [i18n] },
    })
    const pressed = w.findAll('.sa-tf__btn').map((b) => b.attributes('aria-pressed'))
    expect(pressed).toEqual(['false', 'false'])
  })

  it('order keeps the delivered (shuffled) order', () => {
    const w = mount(QuestionRenderer, {
      props: {
        item: item({
          kind: 'order',
          tokens: [
            { id: 't2', text: 'Sprout' },
            { id: 't1', text: 'Seed' },
          ],
        }),
      },
      global: { plugins: [i18n] },
    })
    expect(w.findAll('.sa-order__text').map((n) => n.text())).toEqual(['Sprout', 'Seed'])
  })
})

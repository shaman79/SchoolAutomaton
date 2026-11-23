/**
 * What read-aloud says and in which voice: visible text only, pauses between blocks, math and symbols
 * as words, blanks as a pause, and (in foreign-language content) the practised words in their own
 * language. Rendered through the real markdown/KaTeX pipeline and the real question components.
 */
import { mount } from '@vue/test-utils'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'

import FillBlankQuestion from '@/components/questions/FillBlankQuestion.vue'
import McqQuestion from '@/components/questions/McqQuestion.vue'
import cs from '@/locales/cs.json'
import { renderMarkdown } from '@/lib/safeContent'
import { foreignLanguage } from '@/lib/speechLang'
import { chunkText, speakSymbols, speechSegments, splitClauses } from '@/lib/speechText'
import type { ItemPublic } from '@/types/question'

beforeAll(() => {
  if (!window.matchMedia) {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false, media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    }))
  }
})

const i18n = createI18n({ legacy: false, locale: 'cs', messages: { cs } })

function html(markup: string): HTMLElement {
  const el = document.createElement('div')
  el.innerHTML = markup
  return el
}
const md = (source: string) => html(renderMarkdown(source))
const say = (el: Element, lang = 'cs-CZ', foreign: string | null = null) => speechSegments(el, { lang, foreign })
const text = (el: Element, lang = 'cs-CZ') => say(el, lang).map((s) => s.text).join(' | ')

function mcq(stem: string, options: string[]): HTMLElement {
  const item: ItemPublic = {
    id: 1, item_type: 'mcq', bloom_tier: 1, points: 1, stem_markdown: stem, hint_available: false,
    payload: { kind: 'mcq', multiple: false, options: options.map((t, i) => ({ id: String(i), text: t })) },
  }
  return mount(McqQuestion, { props: { item }, global: { plugins: [i18n] } }).element as HTMLElement
}

describe('speech text', () => {
  it('pauses between heading, paragraph and list items instead of running them together', () => {
    const el = md('## Koloběh vody\n\nVoda se vypařuje\n\n- mraky\n- déšť')
    expect(text(el)).toBe('Koloběh vody, Voda se vypařuje, mraky, déšť')
  })

  it('reads KaTeX math as words, not the MathML digits run together', () => {
    // MathML textContent of \frac{1}{2} is "12" — read as "dvanáct" before.
    expect(text(md('Kolik je $\\frac{1}{2} + \\frac{1}{4}$?'))).toBe('Kolik je 1 lomeno 2 plus 1 lomeno 4?')
    expect(text(md('$x^2 + \\sqrt{16} = 7 \\cdot 8$'))).toBe('x na druhou plus odmocnina z 16 se rovná 7 krát 8')
    expect(text(md('$\\frac{3}{4} \\times 2$'), 'en-GB')).toBe('3 over 4 times 2')
  })

  it('reads the symbols the app writes as words of the language', () => {
    expect(speakSymbols('7 · 8 = 56', 'cs-CZ').trim()).toBe('7 krát 8 se rovná 56')
    expect(speakSymbols('12 : 3 = 4', 'cs-CZ').trim()).toBe('12 děleno 3 se rovná 4')
    expect(speakSymbols('Pozor: venku je −3 °C', 'cs-CZ').trim()).toBe('Pozor: venku je minus 3 °C')
    expect(speakSymbols('1/2 pizzy a 5 - 3', 'cs-CZ').trim()).toBe('1 lomeno 2 pizzy a 5 minus 3')
    expect(speakSymbols('slovo - význam', 'cs-CZ').trim()).toBe('slovo - význam') // a dash stays a dash
    expect(speakSymbols('7 × 8 = 56', 'en').trim()).toBe('7 times 8 equals 56')
    expect(speakSymbols('Super! 🎉👍🏽 voda → pára', 'cs-CZ').trim()).toBe('Super! voda, pára')
    expect(speakSymbols('b_strý', 'cs-CZ').trim()).toBe('b … strý')
  })

  it('skips pictures, diagram labels and buttons, but reads a caption', () => {
    const el = html(
      '<p>Podívej se na obrázek.</p><figure><svg><text>H2O</text></svg><img alt="mrak">' +
        '<figcaption>Koloběh vody</figcaption></figure><button>Přečíst</button><span aria-hidden="true">🔒</span>',
    )
    expect(text(el)).toBe('Podívej se na obrázek. Koloběh vody')
  })

  it('reads a blank as a pause, never the select box and its choices', () => {
    const item: ItemPublic = {
      id: 2, item_type: 'cloze', bloom_tier: 1, points: 1, stem_markdown: 'Doplň písmeno.', hint_available: false,
      payload: { kind: 'cloze', text_template: 'b{{b1}}strý kluk', blanks: [{ id: 'b1', choices: ['y', 'i'] }] },
    }
    const el = mount(FillBlankQuestion, { props: { item }, global: { plugins: [i18n] } }).element as HTMLElement
    const spoken = text(el)
    expect(spoken).toBe('Doplň písmeno. b… strý kluk')
    expect(spoken).not.toContain('Vyber') // the select's placeholder option
  })

  it('pauses between answer options', () => {
    expect(text(mcq('Kolik je 7 · 8?', ['54', '56', '63']))).toBe('Kolik je 7 krát 8? Vyber jednu odpověď, 54, 56, 63')
  })

  it('splits clauses at sentence ends and clause marks, not at decimals or division', () => {
    expect(splitClauses('Doplň: She ___ (play) tennis. Hotovo!')).toEqual(['Doplň:', ' She ___ ', '(play)', ' tennis.', ' Hotovo!'])
    expect(splitClauses('3.5 a 12 : 3')).toEqual(['3.5 a 12 : 3'])
  })
})

describe('language of the speech', () => {
  it('keeps everything in the reading language outside foreign-language content', () => {
    // A single English word in Czech text stays Czech (precision first) …
    expect(say(md('Slovo dog znamená pes.'))).toEqual([{ lang: 'cs-CZ', text: 'Slovo dog znamená pes.' }])
    // … but an unmistakable English sentence (e.g. a review card) gets the English voice.
    expect(say(md('Přelož: The cat is on the table.'))).toEqual([
      { lang: 'cs-CZ', text: 'Přelož:' },
      { lang: 'en', text: 'The cat is on the table.' },
    ])
  })

  it('reads English answer options with an English voice in an English quiz', () => {
    expect(say(mcq('Jak se řekne anglicky „pes“?', ['dog', 'cat', 'horse']), 'cs-CZ', 'en')).toEqual([
      { lang: 'cs-CZ', text: 'Jak se řekne anglicky „pes“? Vyber jednu odpověď' },
      { lang: 'en', text: 'dog, cat, horse' },
    ])
  })

  it('keeps Czech options Czech in the reverse question, and reads the quoted English word in English', () => {
    expect(say(mcq('Jak se řekne česky „dog“?', ['pes', 'kočka', 'kůň']), 'cs-CZ', 'en')).toEqual([
      { lang: 'cs-CZ', text: 'Jak se řekne česky' },
      { lang: 'en', text: '„dog“?' },
      { lang: 'cs-CZ', text: 'Vyber jednu odpověď, pes, kočka, kůň' },
    ])
  })

  it('treats a word quoted after "anglicky" as the Czech word to translate', () => {
    // "kolo" carries no diacritic and is not an English word; the question names the target language.
    const spoken = say(md('Napiš anglicky slovo pro „lano“.'), 'cs-CZ', 'en')
    expect(spoken).toEqual([{ lang: 'cs-CZ', text: 'Napiš anglicky slovo pro „lano“.' }])
    // Without that cue an unknown quoted word in an English lesson is the practised (English) one.
    expect(say(md('Co znamená „lane“?'), 'cs-CZ', 'en')).toEqual([
      { lang: 'cs-CZ', text: 'Co znamená' },
      { lang: 'en', text: '„lane“?' },
    ])
  })

  it('reads an English sentence after Czech instructions in English', () => {
    expect(say(md('Doplň správný tvar slovesa: She ___ (play) tennis.'), 'cs-CZ', 'en')).toEqual([
      { lang: 'cs-CZ', text: 'Doplň správný tvar slovesa:' },
      { lang: 'en', text: 'She… (play) tennis.' },
    ])
  })

  it('alternates voices in a vocabulary list', () => {
    expect(say(md('Zvířata:\n\n- **dog** – pes\n- **cat** – kočka\n- **giraffe** – žirafa'), 'cs-CZ', 'en')).toEqual([
      { lang: 'cs-CZ', text: 'Zvířata:' },
      { lang: 'en', text: 'dog' },
      { lang: 'cs-CZ', text: 'pes' },
      { lang: 'en', text: 'cat' },
      { lang: 'cs-CZ', text: 'kočka' },
      { lang: 'en', text: 'giraffe' },
      { lang: 'cs-CZ', text: 'žirafa' },
    ])
  })

  it('names the practised language from the topic, English by default, nothing outside languages', () => {
    expect(foreignLanguage('foreign_language', ['Anglická slovíčka: zvířata'], 'cs-CZ')).toBe('en')
    expect(foreignLanguage('foreign_language', ['Němčina – členy der, die, das'], 'cs-CZ')).toBe('de')
    expect(foreignLanguage('foreign_language', ['present simple'], 'cs-CZ')).toBe('en')
    expect(foreignLanguage('foreign_language', ['Czech greetings'], 'en-GB')).toBe('cs')
    expect(foreignLanguage('foreign_language', ['greetings'], 'en-GB')).toBeNull()
    expect(foreignLanguage('math', ['anglické jednotky'], 'cs-CZ')).toBeNull()
  })
})

describe('chunkText', () => {
  it('cuts long text into pieces the engines finish, at sentence ends first', () => {
    const sentence = 'Voda se ohřeje sluncem a vypaří se do vzduchu. '
    const chunks = chunkText(sentence.repeat(12))
    expect(chunks.length).toBeGreaterThan(3)
    for (const c of chunks) {
      expect(c.length).toBeLessThanOrEqual(160)
      expect(c.endsWith('.')).toBe(true)
    }
    expect(chunks.join(' ')).toBe(sentence.repeat(12).trim())
  })

  it('falls back to clause marks, then spaces, and never drops text', () => {
    const words = Array.from({ length: 80 }, (_, i) => `slovo${i}`).join(' ')
    const chunks = chunkText(words)
    expect(chunks.every((c) => c.length <= 160)).toBe(true)
    expect(chunks.join(' ')).toBe(words)
    expect(chunkText('  ')).toEqual([])
  })
})

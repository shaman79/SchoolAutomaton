import { describe, expect, it } from 'vitest'

import { pickVoice, speakableText } from '@/composables/useSpeech'
import { speechLang } from '@/lib/speechLang'

const v = (lang: string, name = lang) => ({ lang, name }) as SpeechSynthesisVoice

describe('read-aloud helpers', () => {
  it('picks an exact regional voice, then the same language, never another language', () => {
    const voices = [v('en-US'), v('en-GB'), v('cs-CZ', 'Zuzana')]
    expect(pickVoice(voices, 'en-GB')?.lang).toBe('en-GB')
    expect(pickVoice([v('cs_CZ')], 'cs-CZ')?.lang).toBe('cs_CZ')
    expect(pickVoice([v('en-US')], 'cs-CZ')).toBeNull() // no Czech voice -> no button
  })

  it('reads the education locale for matching content, else the bare language', () => {
    expect(speechLang('cs', 'cs-CZ')).toBe('cs-CZ')
    expect(speechLang('en', 'en-GB')).toBe('en-GB')
    expect(speechLang('en', 'cs-CZ')).toBe('en')
  })

  it('speaks only visible text (no KaTeX duplicates or buttons)', () => {
    const el = document.createElement('div')
    el.innerHTML =
      '<p>Kolik je <span class="katex"><span class="katex-mathml">3·4<annotation>3\\cdot 4</annotation></span><span class="katex-html" aria-hidden="true">3·4</span></span>?</p><button>Přečíst</button>'
    expect(speakableText(el)).toBe('Kolik je 3·4?')
  })
})

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

import { pickVoice, useSpeech } from '@/composables/useSpeech'
import { speechLang } from '@/lib/speechLang'
import { speakableText } from '@/lib/speechText'

const v = (lang: string, name = lang, extra: Partial<SpeechSynthesisVoice> = {}) =>
  ({ lang, name, voiceURI: name, localService: true, default: false, ...extra }) as SpeechSynthesisVoice

describe('read-aloud helpers', () => {
  it('picks an exact regional voice, then the same language, never another language', () => {
    const voices = [v('en-US'), v('en-GB'), v('cs-CZ', 'Zuzana')]
    expect(pickVoice(voices, 'en-GB')?.lang).toBe('en-GB')
    expect(pickVoice([v('cs_CZ')], 'cs-CZ')?.lang).toBe('cs_CZ')
    expect(pickVoice([v('en-US')], 'cs-CZ')).toBeNull() // no Czech voice -> no button
  })

  it('reads a bare language in its usual region (British English for Czech schools)', () => {
    expect(pickVoice([v('en-US'), v('en-IN'), v('en-GB')], 'en')?.lang).toBe('en-GB')
    expect(pickVoice([v('en-US'), v('en-IN')], 'en')?.lang).toBe('en-US') // no GB voice: any English
  })

  it("never picks Apple's novelty voices while a real one exists, and prefers natural voices", () => {
    const bubbles = v('en-GB', 'Bubbles', { voiceURI: 'com.apple.speech.synthesis.voice.Bubbles' })
    const grandpa = v('en-GB', 'Grandpa (English (UK))', { voiceURI: 'com.apple.eloquence.en-GB.Grandpa' })
    const daniel = v('en-GB', 'Daniel', { voiceURI: 'com.apple.voice.compact.en-GB.Daniel' })
    expect(pickVoice([bubbles, grandpa, daniel], 'en-GB')?.name).toBe('Daniel')
    const jakub = v('cs-CZ', 'Microsoft Jakub - Czech (Czech Republic)')
    const vlasta = v('cs-CZ', 'Microsoft Vlasta Online (Natural) - Czech (Czechia)', { localService: false })
    expect(pickVoice([jakub, vlasta], 'cs-CZ')?.name).toContain('Vlasta')
    const google = v('en-GB', 'Google UK English Female', { localService: false })
    expect(pickVoice([google, daniel], 'en-GB')?.name).toBe('Daniel') // on-device before online
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
    expect(speakableText(el)).toBe('Kolik je 3 krát 4?')
  })
})

// ---------------------------------------------------------------- the speech queue
class FakeUtterance {
  voice: SpeechSynthesisVoice | null = null
  lang = ''
  rate = 1
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(public text: string) {}
}

describe('useSpeech', () => {
  const voices = [v('cs-CZ', 'Zuzana'), v('en-GB', 'Daniel')]
  let spoken: FakeUtterance[]
  let synth: {
    speaking: boolean; pending: boolean; paused: boolean
    getVoices: () => SpeechSynthesisVoice[]; speak: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn>
    resume: ReturnType<typeof vi.fn>; addEventListener: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    spoken = []
    synth = {
      speaking: false,
      pending: false,
      paused: false,
      getVoices: () => voices,
      speak: vi.fn((u: FakeUtterance) => {
        spoken.push(u)
        synth.speaking = true
      }),
      cancel: vi.fn(() => {
        synth.speaking = false
      }),
      resume: vi.fn(),
      addEventListener: vi.fn(),
    }
    vi.stubGlobal('speechSynthesis', synth)
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  function withSpeech() {
    let api!: ReturnType<typeof useSpeech>
    mount(defineComponent({ setup: () => ((api = useSpeech()), () => null) }))
    api.stop() // the reading state is shared app-wide; start each test from silence
    return api
  }
  const finish = (u: FakeUtterance) => u.onend?.()

  it('speaks a long reading piece by piece, each piece in its own voice, until the end', () => {
    const speech = withSpeech()
    const long = 'Voda se ohřeje sluncem a vypaří se do vzduchu. '.repeat(10)
    speech.speak('k', [{ text: long, lang: 'cs-CZ' }, { text: 'water cycle', lang: 'en' }], 'cs-CZ')
    expect(speech.speakingKey.value).toBe('k')
    expect(spoken).toHaveLength(1) // one piece at a time
    while (spoken.length && spoken[spoken.length - 1].text !== 'water cycle') finish(spoken[spoken.length - 1])
    expect(spoken.length).toBeGreaterThan(3)
    expect(spoken.slice(0, -1).every((u) => u.text.length <= 160 && u.voice?.name === 'Zuzana' && u.lang === 'cs-CZ')).toBe(true)
    const last = spoken[spoken.length - 1]
    expect([last.voice?.name, last.lang, last.rate]).toEqual(['Daniel', 'en-GB', 0.9])
    finish(last)
    expect(speech.speakingKey.value).toBeNull()
  })

  it('reads a segment with the reading voice when the device has no voice for its language', () => {
    const speech = withSpeech()
    speech.speak('k', [{ text: 'der Hund', lang: 'de' }], 'cs-CZ')
    expect(spoken[0].voice?.name).toBe('Zuzana')
  })

  it('stops for good: a cancelled piece does not start the next one', () => {
    const speech = withSpeech()
    speech.speak('k', [{ text: 'První věta. '.repeat(30), lang: 'cs-CZ' }], 'cs-CZ')
    const first = spoken[0]
    speech.stop()
    expect(synth.cancel).toHaveBeenCalledOnce()
    first.onerror?.() // the engine reports the cancelled piece as interrupted
    expect(spoken).toHaveLength(1)
    expect(speech.speakingKey.value).toBeNull()
  })

  it('skips a piece the engine fails on instead of ending the reading', () => {
    const speech = withSpeech()
    speech.speak('k', [{ text: 'Jedna. '.repeat(40), lang: 'cs-CZ' }], 'cs-CZ')
    spoken[0].onerror?.()
    expect(spoken).toHaveLength(2)
  })

  it('starts the first piece inside the click unless it had to cancel another reading first', () => {
    vi.useFakeTimers()
    const speech = withSpeech()
    speech.speak('a', [{ text: 'Ahoj.', lang: 'cs-CZ' }], 'cs-CZ')
    expect(spoken).toHaveLength(1) // synchronous: iOS needs the user gesture
    speech.speak('b', [{ text: 'Nazdar.', lang: 'cs-CZ' }], 'cs-CZ')
    expect(synth.cancel).toHaveBeenCalledOnce()
    expect(speech.speakingKey.value).toBe('b')
    expect(spoken).toHaveLength(1) // Safari drops an utterance queued right after cancel()
    vi.advanceTimersByTime(150)
    expect(spoken.map((u) => u.text)).toEqual(['Ahoj.', 'Nazdar.'])
    spoken[0].onend?.() // the cancelled reading's late event changes nothing
    expect(spoken).toHaveLength(2)
  })

  it('does nothing without a voice for the reading language', () => {
    const speech = withSpeech()
    speech.speak('k', [{ text: 'Bonjour', lang: 'fr' }], 'fr-FR')
    expect(spoken).toHaveLength(0)
    expect(speech.speakingKey.value).toBeNull()
  })
})

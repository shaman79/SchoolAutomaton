/**
 * Read-aloud (speech synthesis) — for the youngest readers and dyslexic kids. Runs in the browser /
 * OS voice engine (no audio leaves the device for synthesis). Only offered when the device actually
 * has a voice for the content language: a Czech text read by an English voice is worse than nothing.
 *
 * Text is spoken as a queue of short utterances (see `chunkText`): one long utterance stops after
 * about 15 s with Chrome's online voices and fails outright on some Android engines. Each segment is
 * read by a voice of its own language (English words in a Czech lesson by an English voice), falling
 * back to the reading voice when the device has none for that language.
 */
import { onBeforeUnmount, ref } from 'vue'

import { chunkText, type SpeechSegment } from '@/lib/speechText'

const voices = ref<SpeechSynthesisVoice[]>([])
const speakingKey = ref<string | null>(null)
let listening = false
// Each speak() starts a new session; callbacks of an older (cancelled) queue are ignored.
let session = 0
// The engine may drop an utterance it alone references before its events fire (Chrome).
let queue: SpeechSynthesisUtterance[] = []

function loadVoices() {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
  voices.value = window.speechSynthesis.getVoices()
  if (!listening) {
    listening = true
    window.speechSynthesis.addEventListener?.('voiceschanged', () => {
      voices.value = window.speechSynthesis.getVoices()
    })
  }
}

/** BCP-47 with a hyphen ('cs_CZ' from some Android engines -> 'cs-CZ'). */
export function langTag(lang: string): string {
  return lang.replace(/_/g, '-')
}

// The region a bare language is read in when the learner's settings don't say (Czech schools teach
// British English).
const DEFAULT_REGION: Record<string, string> = {
  en: 'en-gb', de: 'de-de', fr: 'fr-fr', es: 'es-es', it: 'it-it', ru: 'ru-ru', pl: 'pl-pl', cs: 'cs-cz', sk: 'sk-sk',
}
// Apple's novelty and "Eloquence" voices (Bubbles, Zarvox, Grandpa …) carry ordinary language tags
// but are joke or robotic voices; never pick them while a real one exists.
const ODD_VOICE =
  /eloquence|speech\.synthesis\.voice\.|\b(albert|bad news|bahh|bells|boing|bubbles|cellos|good news|jester|organ|superstar|trinoids|whisper|wobble|zarvox|junior|ralph|fred|kathy|princess|deranged|hysterical|eddy|flo|grandma|grandpa|reed|rocko|sandy|shelley)\b/i

/** The best installed voice for a BCP-47 tag: the wanted region first, then the same language;
 *  within those, natural/neural voices, then on-device ones, never a novelty voice if avoidable. */
export function pickVoice(list: SpeechSynthesisVoice[], lang: string): SpeechSynthesisVoice | null {
  const want = langTag(lang).toLowerCase()
  const base = want.split('-')[0]
  const region = want.includes('-') ? want : DEFAULT_REGION[base]
  const tag = (v: SpeechSynthesisVoice) => langTag(v.lang).toLowerCase()
  const rank = (v: SpeechSynthesisVoice) =>
    (tag(v) === region ? 0 : 100) +
    (ODD_VOICE.test(`${v.voiceURI ?? ''} ${v.name}`) ? 50 : 0) +
    (/natural|neural|premium|enhanced|online/i.test(v.name) ? 0 : v.localService ? 1 : 2)
  let best: SpeechSynthesisVoice | null = null
  for (const v of list) {
    if (tag(v).split('-')[0] !== base) continue
    if (!best || rank(v) < rank(best)) best = v
  }
  return best
}

export function useSpeech() {
  loadVoices()

  function voiceFor(lang: string) {
    return pickVoice(voices.value, lang)
  }

  /** Stop whatever is being read; true when the engine actually had something to cancel. */
  function halt(): boolean {
    session++
    queue = []
    speakingKey.value = null
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return false
    const synth = window.speechSynthesis
    if (!synth.speaking && !synth.pending) return false
    synth.cancel()
    return true
  }

  function stop() {
    halt()
  }

  /** Speak `segments` (each in its own language) as a queue of short utterances. `lang` is the
   *  reading language: its voice reads segments whose own language has no voice on this device. */
  function speak(key: string, segments: SpeechSegment[], lang: string) {
    const fallback = voiceFor(lang)
    if (!fallback) return
    const utterances: SpeechSynthesisUtterance[] = []
    for (const segment of segments) {
      const voice = voiceFor(segment.lang) ?? fallback
      for (const chunk of chunkText(segment.text)) {
        const u = new SpeechSynthesisUtterance(chunk)
        u.voice = voice
        u.lang = langTag(voice.lang)
        u.rate = 0.9 // a little slower for children
        utterances.push(u)
      }
    }
    if (!utterances.length) return
    const cancelled = halt()
    const mine = session
    queue = utterances
    speakingKey.value = key
    const play = (i: number) => {
      if (mine !== session) return
      const u = queue[i]
      if (!u) {
        speakingKey.value = null
        return
      }
      // An error on one piece (e.g. 'synthesis-failed') skips it rather than ending the reading; a
      // cancel bumps the session first, so its 'interrupted' error is ignored above.
      u.onend = u.onerror = () => play(i + 1)
      window.speechSynthesis.speak(u)
    }
    // Chrome can be left paused after a cancel.
    if (window.speechSynthesis.paused) window.speechSynthesis.resume()
    // The first piece is spoken inside the click handler (iOS only starts speech from a user
    // gesture) — unless another reading was just cancelled: Safari drops an utterance queued right
    // after cancel(), and speech is already unlocked then, so start a moment later.
    if (cancelled) window.setTimeout(() => play(0), 120)
    else play(0)
  }

  onBeforeUnmount(stop)
  return { voiceFor, speak, stop, speakingKey }
}

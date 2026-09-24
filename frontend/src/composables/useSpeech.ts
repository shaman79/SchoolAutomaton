/**
 * Read-aloud (speech synthesis) — for the youngest readers and dyslexic kids. Runs in the browser /
 * OS voice engine (no audio leaves the device for synthesis). Only offered when the device actually
 * has a voice for the content language: a Czech text read by an English voice is worse than nothing.
 */
import { onBeforeUnmount, ref } from 'vue'

const voices = ref<SpeechSynthesisVoice[]>([])
const speakingKey = ref<string | null>(null)
let listening = false

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

/** The best installed voice for a BCP-47 tag (exact region first, then same language). */
export function pickVoice(list: SpeechSynthesisVoice[], lang: string): SpeechSynthesisVoice | null {
  const want = lang.toLowerCase()
  const base = want.split('-')[0]
  return (
    list.find((v) => v.lang.toLowerCase().replace('_', '-') === want) ??
    list.find((v) => v.lang.toLowerCase().split(/[-_]/)[0] === base) ??
    null
  )
}

/** Spoken text for a rendered element: visible text only (no KaTeX duplicates, no buttons). */
export function speakableText(el: HTMLElement): string {
  const copy = el.cloneNode(true) as HTMLElement
  copy.querySelectorAll('.katex-html, annotation, button, [aria-hidden="true"], .sa-readaloud').forEach((n) => n.remove())
  return (copy.textContent ?? '').replace(/\s+/g, ' ').trim()
}

export function useSpeech() {
  loadVoices()

  function voiceFor(lang: string) {
    return pickVoice(voices.value, lang)
  }

  function stop() {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
    speakingKey.value = null
  }

  function speak(key: string, text: string, lang: string) {
    const voice = voiceFor(lang)
    if (!voice || !text) return
    stop()
    const u = new SpeechSynthesisUtterance(text)
    u.voice = voice
    u.lang = voice.lang
    u.rate = 0.9 // a little slower for children
    u.onend = u.onerror = () => {
      if (speakingKey.value === key) speakingKey.value = null
    }
    speakingKey.value = key
    window.speechSynthesis.speak(u)
  }

  onBeforeUnmount(stop)
  return { voiceFor, speak, stop, speakingKey }
}

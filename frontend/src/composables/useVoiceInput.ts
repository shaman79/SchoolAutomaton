/**
 * Dictation for the prompt box (Web Speech recognition) — for children who can't type well yet.
 * Browsers implement it with a cloud service (Chrome sends the audio to Google), so it is OFF by
 * default and switched on by a parent in Settings; the UI says so. Unsupported browsers get nothing.
 */
import { onBeforeUnmount, ref } from 'vue'

type Recognition = {
  lang: string
  interimResults: boolean
  maxAlternatives: number
  start(): void
  stop(): void
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
}

function ctor(): (new () => Recognition) | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as Record<string, unknown>
  return ((w.SpeechRecognition ?? w.webkitSpeechRecognition) as new () => Recognition) ?? null
}

export function voiceInputSupported(): boolean {
  return ctor() !== null
}

export function useVoiceInput(onText: (text: string) => void) {
  const listening = ref(false)
  let rec: Recognition | null = null

  function start(lang: string) {
    const C = ctor()
    if (!C || listening.value) return
    rec = new C()
    rec.lang = lang
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.onresult = (e) => {
      const text = Array.from(e.results).map((r) => r[0]?.transcript ?? '').join(' ').trim()
      if (text) onText(text)
    }
    rec.onend = rec.onerror = () => {
      listening.value = false
    }
    listening.value = true
    rec.start()
  }

  function stop() {
    rec?.stop()
    listening.value = false
  }

  onBeforeUnmount(stop)
  return { listening, start, stop }
}

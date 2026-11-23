<script setup lang="ts">
/**
 * 🔊 "Přečíst" — reads the target element aloud in the content language; toggles to "Zastavit".
 * Renders nothing when the device has no voice for that language. In a foreign-language lesson or
 * quiz (`foreign`), the practised words are read by a voice of that language when the device has one.
 */
import { computed, getCurrentInstance } from 'vue'
import { useI18n } from 'vue-i18n'

import { useSpeech } from '@/composables/useSpeech'
import { speechSegments } from '@/lib/speechText'

const props = defineProps<{
  /** Element whose visible text is read. */
  target: HTMLElement | null
  /** BCP-47 language of the content (e.g. 'cs-CZ'). */
  lang: string
  /** Language the content practises (bare code, from `foreignLanguage`), if any. */
  foreign?: string | null
}>()

const { t } = useI18n()
const { voiceFor, speak, stop, speakingKey } = useSpeech()
const key = `ra-${getCurrentInstance()?.uid ?? Math.random()}`

const available = computed(() => !!voiceFor(props.lang))
const speaking = computed(() => speakingKey.value === key)

function toggle() {
  if (speaking.value) return stop()
  if (props.target) speak(key, speechSegments(props.target, { lang: props.lang, foreign: props.foreign }), props.lang)
}
</script>

<template>
  <button
    v-if="available"
    type="button"
    class="sa-readaloud"
    :aria-pressed="speaking"
    @click="toggle"
  >
    <span aria-hidden="true">{{ speaking ? '⏹' : '🔊' }}</span>
    {{ speaking ? t('speech.stop') : t('speech.read') }}
  </button>
</template>

<style scoped>
.sa-readaloud {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: var(--tap-min);
  padding: 0.3rem 0.75rem;
  border-radius: var(--radius-pill);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  font: inherit;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-ink);
  cursor: pointer;
}
.sa-readaloud[aria-pressed='true'] {
  border-color: var(--color-primary);
}
</style>

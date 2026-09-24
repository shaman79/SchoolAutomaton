<script setup lang="ts">
/**
 * 🔊 "Přečíst" — reads the target element aloud in the content language; toggles to "Zastavit".
 * Renders nothing when the device has no voice for that language.
 */
import { computed, getCurrentInstance } from 'vue'
import { useI18n } from 'vue-i18n'

import { speakableText, useSpeech } from '@/composables/useSpeech'

const props = defineProps<{
  /** Element whose visible text is read. */
  target: HTMLElement | null
  /** BCP-47 language of the content (e.g. 'cs-CZ'). */
  lang: string
}>()

const { t } = useI18n()
const { voiceFor, speak, stop, speakingKey } = useSpeech()
const key = `ra-${getCurrentInstance()?.uid ?? Math.random()}`

const available = computed(() => !!voiceFor(props.lang))
const speaking = computed(() => speakingKey.value === key)

function toggle() {
  if (speaking.value) return stop()
  if (props.target) speak(key, speakableText(props.target), props.lang)
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

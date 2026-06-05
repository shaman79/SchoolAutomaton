<script setup lang="ts">
/**
 * Short free-text answer (LLM-graded server-side). A single-line input (or textarea for
 * longer responses). Value emitted is the trimmed string.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type { AnswerEvent, ItemPublic, ShortAnswerPayload } from '@/types/question'
import type { GradeResult } from '@/types/session'

const props = withDefaults(
  defineProps<{
    item: ItemPublic
    disabled?: boolean
    feedback?: GradeResult | null
    sound?: boolean
    multiline?: boolean
  }>(),
  { disabled: false, feedback: null, sound: false, multiline: false },
)

const emit = defineEmits<{ (e: 'answer', payload: AnswerEvent): void }>()

const { t } = useI18n()
const payload = computed(() => props.item.payload as ShortAnswerPayload)
const timing = useAnswerTiming(() => props.item.id)

const text = ref('')
watch(
  () => props.item.id,
  () => {
    text.value = ''
    timing.reset()
  },
)

const locked = computed(() => props.disabled || !!props.feedback)
const canSubmit = computed(() => text.value.trim().length > 0 && !locked.value)

function submit() {
  if (!canSubmit.value) return
  emit('answer', timing.buildEvent(text.value.trim()))
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />

    <textarea
      v-if="multiline"
      v-model="text"
      class="sa-sa__input sa-sa__textarea"
      rows="3"
      :placeholder="payload.placeholder ?? t('q.short.placeholder')"
      :disabled="locked"
      :aria-label="t('q.short.label')"
    />
    <input
      v-else
      v-model="text"
      type="text"
      class="sa-sa__input"
      :placeholder="payload.placeholder ?? t('q.short.placeholder')"
      :disabled="locked"
      :aria-label="t('q.short.label')"
      @keyup.enter="submit"
    />

    <button class="sa-btn sa-btn-primary sa-q__check" :disabled="!canSubmit" @click="submit">
      {{ t('common.check') }}
    </button>

    <AnswerFeedback
      v-if="feedback"
      :correct="feedback.is_correct"
      :partial="feedback.partial_credit"
      :feedback="feedback.feedback"
      :explanation="feedback.explanation"
      :misconception="feedback.misconception"
      :sound="sound"
    />
  </div>
</template>

<style scoped>
.sa-q {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.1rem;
}
.sa-sa__input {
  min-height: var(--tap-min);
  padding: 0.65rem 0.9rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
  font: inherit;
  color: var(--color-ink);
  width: 100%;
}
.sa-sa__textarea {
  resize: vertical;
  line-height: 1.5;
}
.sa-sa__input:focus {
  border-color: var(--color-primary);
}
.sa-q__check {
  align-self: flex-start;
}
</style>

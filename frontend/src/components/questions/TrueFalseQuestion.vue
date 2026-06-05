<script setup lang="ts">
/**
 * True / False. Two large toggle buttons (aria-pressed, matching the MCQ/hotspot pattern). Value
 * emitted is a boolean. Each button is independently Tab-focusable and toggled with Enter/Space.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type { AnswerEvent, ItemPublic, TrueFalsePayload } from '@/types/question'
import type { GradeResult } from '@/types/session'

const props = withDefaults(
  defineProps<{
    item: ItemPublic
    disabled?: boolean
    feedback?: GradeResult | null
    sound?: boolean
    managed?: boolean
  }>(),
  { disabled: false, feedback: null, sound: false, managed: false },
)

const emit = defineEmits<{ (e: 'answer', payload: AnswerEvent): void }>()

const { t } = useI18n()
const payload = computed(() => props.item.payload as TrueFalsePayload)
const timing = useAnswerTiming(() => props.item.id)

const choice = ref<boolean | null>(null)
watch(
  () => props.item.id,
  () => {
    choice.value = null
    timing.reset()
  },
)

const locked = computed(() => props.disabled || !!props.feedback)

function pick(v: boolean) {
  if (locked.value) return
  choice.value = v
}

const canSubmit = computed(() => choice.value !== null && !locked.value)
defineExpose({ submit, canSubmit })
function submit() {
  if (!canSubmit.value) return
  emit('answer', timing.buildEvent(choice.value as boolean))
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />
    <SafeContent
      v-if="payload.statement"
      :markdown="payload.statement"
      prose
      class="sa-q__statement"
    />

    <div class="sa-tf" role="group" :aria-label="t('q.tf.legend')">
      <button
        type="button"
        class="sa-btn sa-tf__btn"
        :class="choice === true ? 'sa-tf__btn--on' : 'sa-btn-ghost'"
        :aria-pressed="choice === true"
        :disabled="locked"
        @click="pick(true)"
      >
        <span aria-hidden="true">✓</span> {{ t('q.tf.true') }}
      </button>
      <button
        type="button"
        class="sa-btn sa-tf__btn"
        :class="choice === false ? 'sa-tf__btn--on' : 'sa-btn-ghost'"
        :aria-pressed="choice === false"
        :disabled="locked"
        @click="pick(false)"
      >
        <span aria-hidden="true">✕</span> {{ t('q.tf.false') }}
      </button>
    </div>

    <button v-if="!feedback && !managed" class="sa-btn sa-btn-primary sa-q__check" :disabled="!canSubmit" @click="submit">
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
.sa-tf {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr));
  gap: 0.75rem;
}
.sa-tf__btn {
  font-size: 1.05rem;
  padding: 0.9rem 1rem;
  border: 2px solid var(--color-line);
}
.sa-tf__btn--on {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.sa-q__check {
  align-self: stretch;
  width: 100%;
}
@media (min-width: 640px) {
  .sa-q__check {
    align-self: flex-start;
    width: auto;
  }
}
@media (max-width: 360px) {
  .sa-tf {
    grid-template-columns: 1fr;
  }
}
</style>

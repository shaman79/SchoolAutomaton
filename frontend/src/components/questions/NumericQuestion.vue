<script setup lang="ts">
/**
 * Numeric answer. inputmode="decimal" => mobile numeric keypad; the field accepts negative
 * and decimal values. Value emitted is a number (null guarded by the submit gate). Optional
 * unit is shown beside the field (display only — backend grades the number).
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type { AnswerEvent, ItemPublic, NumericPayload } from '@/types/question'
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
const payload = computed(() => props.item.payload as NumericPayload)
const timing = useAnswerTiming(() => props.item.id)

// Keep as string so we can validate before coercing; supports comma decimal too.
const raw = ref('')
watch(
  () => props.item.id,
  () => {
    raw.value = ''
    timing.reset()
  },
)

const locked = computed(() => props.disabled || !!props.feedback)

const parsed = computed<number | null>(() => {
  const s = raw.value.trim().replace(',', '.')
  if (s === '' || s === '-' || s === '.' || s === '-.') return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
})

const canSubmit = computed(() => parsed.value !== null && !locked.value)
defineExpose({ submit, canSubmit })

function submit() {
  if (!canSubmit.value || parsed.value === null) return
  emit('answer', timing.buildEvent(parsed.value))
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />

    <div class="sa-num">
      <input
        v-model="raw"
        type="text"
        inputmode="decimal"
        autocomplete="off"
        class="sa-num__input"
        :disabled="locked"
        :aria-label="t('q.numeric.label')"
        :aria-describedby="payload.unit ? `unit-${item.id}` : undefined"
        @keyup.enter="submit"
      />
      <span v-if="payload.unit" :id="`unit-${item.id}`" class="sa-num__unit">
        {{ payload.unit }}
      </span>
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
.sa-num {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.sa-num__input {
  min-height: var(--tap-min);
  padding: 0.65rem 0.9rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
  font: inherit;
  font-size: 1.2rem;
  color: var(--color-ink);
  width: min(9rem, 100%);
  box-sizing: border-box;
  text-align: center;
}
.sa-num__input:focus {
  border-color: var(--color-primary);
}
.sa-num__unit {
  font-weight: 600;
  color: var(--color-ink-soft);
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
</style>

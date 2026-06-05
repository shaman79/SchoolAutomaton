<script setup lang="ts">
/**
 * Multiple choice (single-select radio semantics OR multi-select checkbox semantics, by
 * payload.multiple). Big tap targets (>=44px), keyboard accessible (native radio/checkbox
 * inputs), aria-live feedback via AnswerFeedback. Emits AnswerEvent with value = option id
 * (single) or option ids[] (multi).
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type { AnswerEvent, ItemPublic, McqPayload } from '@/types/question'
import type { GradeResult } from '@/types/session'

const props = withDefaults(
  defineProps<{
    item: ItemPublic
    disabled?: boolean
    feedback?: GradeResult | null
    sound?: boolean
  }>(),
  { disabled: false, feedback: null, sound: false },
)

const emit = defineEmits<{ (e: 'answer', payload: AnswerEvent): void }>()

const { t } = useI18n()
const payload = computed(() => props.item.payload as McqPayload)
const timing = useAnswerTiming(() => props.item.id)

const selected = ref<Set<string>>(new Set())
watch(
  () => props.item.id,
  () => {
    selected.value = new Set()
    timing.reset()
  },
)

const locked = computed(() => props.disabled || !!props.feedback)

function toggle(id: string) {
  if (locked.value) return
  const next = new Set(payload.value.multiple ? selected.value : [])
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

const canSubmit = computed(() => selected.value.size > 0 && !locked.value)

function submit() {
  if (!canSubmit.value) return
  const ids = [...selected.value]
  const value = payload.value.multiple ? ids : ids[0]
  emit('answer', timing.buildEvent(value))
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />

    <fieldset class="sa-q__options" :disabled="locked">
      <legend class="sr-only">
        {{ payload.multiple ? t('q.mcq.select_all') : t('q.mcq.select_one') }}
      </legend>
      <label
        v-for="opt in payload.options"
        :key="opt.id"
        class="sa-option"
        :class="{ 'sa-option--checked': selected.has(opt.id) }"
      >
        <input
          :type="payload.multiple ? 'checkbox' : 'radio'"
          :name="`mcq-${item.id}`"
          :value="opt.id"
          :checked="selected.has(opt.id)"
          class="sa-option__input"
          @change="toggle(opt.id)"
        />
        <span class="sa-option__box" aria-hidden="true" />
        <SafeContent :markdown="opt.text" tag="span" class="sa-option__text" />
      </label>
    </fieldset>

    <button v-if="!feedback" class="sa-btn sa-btn-primary sa-q__check" :disabled="!canSubmit" @click="submit">
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
.sa-q__options {
  border: 0;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-option {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: var(--tap-min);
  padding: 0.7rem 0.9rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}
.sa-option--checked {
  border-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface));
}
.sa-option__input {
  position: absolute;
  opacity: 0;
  width: 1px;
  height: 1px;
}
.sa-option__box {
  flex: none;
  width: 1.4rem;
  height: 1.4rem;
  border: 2px solid var(--color-ink-soft);
  border-radius: 0.4rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.sa-option--checked .sa-option__box {
  border-color: var(--color-primary);
  background: var(--color-primary);
}
.sa-option--checked .sa-option__box::after {
  content: '✓';
  color: var(--color-on-primary);
  font-size: 0.9rem;
  line-height: 1;
}
/* Visible focus on the (visually-hidden) input reflects onto the visual box. */
.sa-option__input:focus-visible + .sa-option__box {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
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
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>

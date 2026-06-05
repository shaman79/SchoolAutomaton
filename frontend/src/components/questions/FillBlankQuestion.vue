<script setup lang="ts">
/**
 * Cloze / fill-in-the-blank. Renders text_template, splitting on {{blank_id}} markers and
 * dropping an inline control per blank:
 *   - blank.choices present  => a <select> (select-to-fill; works pointer + keyboard, WCAG 2.1.1)
 *   - blank.choices absent   => a type-in <input>
 * Value emitted is Record<blankId, string>. Prose around the blanks is rendered with
 * SafeContent (segment by segment) so it stays sanitized while inputs sit inline.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type { AnswerEvent, ClozePayload, ItemPublic } from '@/types/question'
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
const payload = computed(() => props.item.payload as ClozePayload)
const timing = useAnswerTiming(() => props.item.id)

const answers = ref<Record<string, string>>({})
watch(
  () => props.item.id,
  () => {
    answers.value = {}
    timing.reset()
  },
  { immediate: true },
)

const locked = computed(() => props.disabled || !!props.feedback)

// Parse template into ordered segments of plain text + blank markers.
type Segment = { type: 'text'; text: string } | { type: 'blank'; id: string }
const segments = computed<Segment[]>(() => {
  const out: Segment[] = []
  const re = /\{\{\s*([\w-]+)\s*\}\}/g
  const tpl = payload.value.text_template ?? ''
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(tpl)) !== null) {
    if (m.index > last) out.push({ type: 'text', text: tpl.slice(last, m.index) })
    out.push({ type: 'blank', id: m[1] })
    last = re.lastIndex
  }
  if (last < tpl.length) out.push({ type: 'text', text: tpl.slice(last) })
  return out
})

function blankDef(id: string) {
  return payload.value.blanks.find((b) => b.id === id) ?? null
}

// Running 1-based blank number per blank id (text segments don't consume a number) for aria-labels.
const blankNumbers = computed<Record<string, number>>(() => {
  const map: Record<string, number> = {}
  let n = 0
  for (const seg of segments.value) {
    if (seg.type === 'blank') map[seg.id] = ++n
  }
  return map
})

const canSubmit = computed(
  () =>
    !locked.value &&
    payload.value.blanks.every((b) => (answers.value[b.id] ?? '').trim().length > 0),
)

function submit() {
  if (!canSubmit.value) return
  // Trim values into the Record<blankId,string> the backend expects.
  const value: Record<string, string> = {}
  for (const b of payload.value.blanks) value[b.id] = (answers.value[b.id] ?? '').trim()
  emit('answer', timing.buildEvent(value))
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />

    <p class="sa-cloze" :aria-label="t('q.cloze.legend')">
      <template v-for="(seg, i) in segments" :key="i">
        <SafeContent v-if="seg.type === 'text'" :markdown="seg.text" tag="span" />
        <template v-else>
          <!-- choices present => select-to-fill (keyboard friendly) -->
          <select
            v-if="blankDef(seg.id)?.choices"
            v-model="answers[seg.id]"
            class="sa-cloze__select"
            :disabled="locked"
            :aria-label="t('q.cloze.blank_n', { n: blankNumbers[seg.id] })"
          >
            <option value="" disabled>{{ t('q.cloze.choose') }}</option>
            <option v-for="c in blankDef(seg.id)?.choices ?? []" :key="c" :value="c">
              {{ c }}
            </option>
          </select>
          <!-- no choices => type-in -->
          <input
            v-else
            v-model="answers[seg.id]"
            type="text"
            class="sa-cloze__input"
            autocapitalize="off"
            autocomplete="off"
            spellcheck="false"
            :disabled="locked"
            :aria-label="t('q.cloze.blank_n', { n: blankNumbers[seg.id] })"
            @keyup.enter="submit"
          />
        </template>
      </template>
    </p>

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
.sa-cloze {
  line-height: 2.4;
  font-size: 1.05rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem 0;
}
.sa-cloze :deep(span) {
  white-space: pre-wrap;
}
.sa-cloze__input,
.sa-cloze__select {
  min-height: var(--tap-min);
  margin: 0 0.15rem;
  padding: 0.25rem 0.6rem;
  border: 2px solid var(--color-primary);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
  font: inherit;
  color: var(--color-ink);
  box-sizing: border-box;
  max-width: 100%;
}
.sa-cloze__input {
  min-width: min(6rem, 40%);
}
.sa-cloze__input:disabled,
.sa-cloze__select:disabled {
  border-color: var(--color-line);
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

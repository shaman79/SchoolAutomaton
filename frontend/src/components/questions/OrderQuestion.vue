<script setup lang="ts">
/**
 * Sequencing / ordering. Drag-drop via vuedraggable (pointer + touch) WITH a mandatory
 * keyboard fallback (WCAG 2.1.1): each row exposes Move-up / Move-down buttons, and the
 * grab handle responds to ArrowUp/ArrowDown when focused. Value emitted is the ordered
 * list of token ids (string[]).
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import draggable from 'vuedraggable'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type { AnswerEvent, ItemPublic, OrderPayload, OrderToken } from '@/types/question'
import type { GradeResult } from '@/types/session'

const props = withDefaults(
  defineProps<{
    item: ItemPublic
    disabled?: boolean
    feedback?: GradeResult | null
    sound?: boolean
    managed?: boolean
    /** The answer already submitted for this item, replayed on resume (see QuestionRenderer). */
    submitted?: unknown
  }>(),
  { disabled: false, feedback: null, sound: false, managed: false },
)

const emit = defineEmits<{ (e: 'answer', payload: AnswerEvent): void }>()

const { t } = useI18n()
const payload = computed(() => props.item.payload as OrderPayload)
const timing = useAnswerTiming(() => props.item.id)

/** The delivered (shuffled) tokens, or — for a replayed answer — in the order the learner left them. */
function fromSubmitted(): OrderToken[] {
  const all = payload.value.tokens
  const ids = Array.isArray(props.submitted) ? props.submitted.map(String) : []
  const ordered = ids
    .map((id) => all.find((tk) => tk.id === id))
    .filter((tk): tk is OrderToken => tk != null)
  return [...ordered, ...all.filter((tk) => !ordered.includes(tk))]
}

const tokens = ref<OrderToken[]>([])
watch(
  () => props.item.id,
  () => {
    tokens.value = fromSubmitted()
    timing.reset()
  },
  { immediate: true },
)
// A replayed answer can arrive after mount (the resume state loads alongside the content).
watch(
  () => props.submitted,
  () => {
    tokens.value = fromSubmitted()
  },
)

const locked = computed(() => props.disabled || !!props.feedback)
// An arrangement is always submittable (you can always reorder), so readiness == not locked.
const canSubmit = computed(() => !locked.value)
defineExpose({ submit, canSubmit })

function move(index: number, dir: -1 | 1) {
  if (locked.value) return
  const to = index + dir
  if (to < 0 || to >= tokens.value.length) return
  const next = [...tokens.value]
  const [moved] = next.splice(index, 1)
  next.splice(to, 0, moved)
  tokens.value = next
}

function onHandleKey(e: KeyboardEvent, index: number) {
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(index, -1)
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    move(index, 1)
  }
}

function submit() {
  if (locked.value) return
  emit('answer', timing.buildEvent(tokens.value.map((tk) => tk.id)))
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />
    <p class="sa-q__hint">{{ t('q.order.instructions') }}</p>

    <draggable
      v-model="tokens"
      item-key="id"
      tag="ol"
      class="sa-order"
      :disabled="locked"
      handle=".sa-order__handle"
      :animation="0"
      ghost-class="sa-order__ghost"
    >
      <template #item="{ element, index }">
        <li class="sa-order__row">
          <span
            class="sa-order__handle"
            role="button"
            tabindex="0"
            :aria-label="t('q.order.reorder', { item: element.text, pos: index + 1 })"
            @keydown="onHandleKey($event, index)"
          >
            <!-- grip + position share one 44px handle, leaving the text room on narrow phones -->
            <span class="sa-order__grip" aria-hidden="true">⠿</span>
            <span class="sa-order__pos" aria-hidden="true">{{ index + 1 }}.</span>
          </span>
          <SafeContent :markdown="element.text" tag="span" class="sa-order__text" />
          <span class="sa-order__moves">
            <button
              type="button"
              class="sa-tap sa-order__move"
              :disabled="locked || index === 0"
              :aria-label="t('q.order.move_up', { item: element.text })"
              @click="move(index, -1)"
            >
              <span aria-hidden="true">▲</span>
            </button>
            <button
              type="button"
              class="sa-tap sa-order__move"
              :disabled="locked || index === tokens.length - 1"
              :aria-label="t('q.order.move_down', { item: element.text })"
              @click="move(index, 1)"
            >
              <span aria-hidden="true">▼</span>
            </button>
          </span>
        </li>
      </template>
    </draggable>

    <button v-if="!feedback && !managed" class="sa-btn sa-btn-primary sa-q__check" :disabled="locked" @click="submit">
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
.sa-q__hint {
  color: var(--color-ink-soft);
  font-size: 0.9rem;
  margin: 0;
}
.sa-order {
  container: sa-order / inline-size;
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
/* Narrow (a small phone or big text): the arrows go under the text, which keeps the full width
   beside the handle. With room for the text between handle and arrows, all three share one line. */
.sa-order__row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas: 'handle text' 'handle moves';
  align-items: center;
  gap: 0.35rem 0.55rem;
  min-height: var(--tap-min);
  padding: 0.5rem 0.65rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
}
.sa-order__ghost {
  opacity: 0.5;
  border-style: dashed;
  border-color: var(--color-primary);
}
.sa-order__handle {
  grid-area: handle;
  cursor: grab;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: var(--tap-min);
  min-height: var(--tap-min);
  line-height: 1.1;
  touch-action: none;
}
.sa-order__grip {
  color: var(--color-ink-soft);
  font-size: 0.95rem;
}
.sa-order__pos {
  font-weight: 700;
  color: var(--color-primary-strong);
}
.sa-order__text {
  grid-area: text;
  min-width: 0;
  overflow-wrap: anywhere; /* a long word wraps instead of running under the buttons */
}
.sa-order__moves {
  grid-area: moves;
  justify-self: end;
  display: flex;
  gap: 0.25rem;
}
@container sa-order (min-width: 14rem) {
  .sa-order__row {
    grid-template-columns: auto minmax(0, 1fr) auto;
    grid-template-areas: 'handle text moves';
  }
  .sa-order__moves {
    flex-direction: column; /* ▲ above ▼, so the text keeps the width */
  }
}
@container sa-order (min-width: 26rem) {
  .sa-order__moves {
    flex-direction: row;
  }
}
.sa-order__move {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface-2);
  color: var(--color-ink);
  cursor: pointer;
}
.sa-order__move:disabled {
  opacity: 0.35;
  cursor: default;
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

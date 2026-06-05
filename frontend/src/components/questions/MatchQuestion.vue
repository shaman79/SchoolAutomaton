<script setup lang="ts">
/**
 * Matching / pairing (left <-> right). Two interaction paths, both always available:
 *   - DRAG: right-side tokens are draggable (vuedraggable) into a left row's drop slot (pointer/touch).
 *   - SELECT-THEN-PLACE (mandatory keyboard/click fallback, WCAG 2.1.1): activate a right token to
 *     "pick it up", then activate a left slot to place it. Works with keyboard + screen readers.
 * Value emitted is the list of { left_id, right_id } pairs the learner formed.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import draggable from 'vuedraggable'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type { AnswerEvent, ItemPublic, MatchPayload, MatchSide } from '@/types/question'
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
const payload = computed(() => props.item.payload as MatchPayload)
const timing = useAnswerTiming(() => props.item.id)

// placed[leftId] = the right token currently in that slot (or null). Pool = unplaced right tokens.
const placed = ref<Record<string, MatchSide | null>>({})
const pool = ref<MatchSide[]>([])
const picked = ref<MatchSide | null>(null) // select-then-place "in hand" token

function init() {
  placed.value = Object.fromEntries(payload.value.left.map((l) => [l.id, null]))
  pool.value = [...payload.value.right]
  picked.value = null
  timing.reset()
}
watch(() => props.item.id, init, { immediate: true })

const locked = computed(() => props.disabled || !!props.feedback)

function rightOf(leftId: string): MatchSide | null {
  return placed.value[leftId] ?? null
}

// --- select-then-place ---
function togglePick(token: MatchSide) {
  if (locked.value) return
  picked.value = picked.value?.id === token.id ? null : token
}

function placeInto(leftId: string) {
  if (locked.value) return
  // If a slot already holds a token, return it to the pool first.
  const existing = placed.value[leftId]
  if (picked.value) {
    if (existing) pool.value.push(existing)
    // remove picked from wherever it is (pool or another slot)
    pool.value = pool.value.filter((tk) => tk.id !== picked.value!.id)
    for (const lid of Object.keys(placed.value)) {
      if (placed.value[lid]?.id === picked.value.id) placed.value[lid] = null
    }
    placed.value[leftId] = picked.value
    picked.value = null
  } else if (existing) {
    // No token in hand but slot occupied => pick it back up (clear the slot).
    placed.value[leftId] = null
    pool.value.push(existing)
  }
}

// --- drag (vuedraggable) ---
// Each left slot is its own single-item draggable list; the shared group lets tokens move
// between the pool and any slot. We re-sync after a change.
function slotList(leftId: string) {
  const v = placed.value[leftId]
  return v ? [v] : []
}
function onSlotChange(leftId: string, list: MatchSide[]) {
  // keep at most one; bump any displaced token back to the pool
  if (list.length > 1) {
    const keep = list[list.length - 1]
    for (const tk of list) if (tk.id !== keep.id) pool.value.push(tk)
    placed.value[leftId] = keep
  } else {
    placed.value[leftId] = list[0] ?? null
  }
}

const allPlaced = computed(() =>
  payload.value.left.every((l) => placed.value[l.id] != null),
)
const canSubmit = computed(() => allPlaced.value && !locked.value)

function submit() {
  if (!canSubmit.value) return
  const pairs = payload.value.left
    .map((l) => ({ left_id: l.id, right_id: placed.value[l.id]?.id ?? '' }))
    .filter((p) => p.right_id)
  emit('answer', timing.buildEvent(pairs))
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />
    <p class="sa-q__hint">{{ t('q.match.instructions') }}</p>

    <div class="sa-match">
      <!-- LEFT column: prompts + drop slots -->
      <ul class="sa-match__left">
        <li v-for="left in payload.left" :key="left.id" class="sa-match__row">
          <SafeContent :markdown="left.text" tag="span" class="sa-match__leftlabel" />
          <draggable
            :model-value="slotList(left.id)"
            item-key="id"
            tag="div"
            class="sa-match__slot"
            :class="{
              'sa-match__slot--target': !!picked && !rightOf(left.id),
              'sa-match__slot--filled': !!rightOf(left.id),
            }"
            group="match"
            :disabled="locked"
            :animation="0"
            role="button"
            :tabindex="locked ? -1 : 0"
            :aria-label="
              rightOf(left.id)
                ? t('q.match.slot_filled', { left: left.text, right: rightOf(left.id)?.text })
                : t('q.match.slot_empty', { left: left.text })
            "
            @update:model-value="onSlotChange(left.id, $event)"
            @click="placeInto(left.id)"
            @keydown.enter.prevent="placeInto(left.id)"
            @keydown.space.prevent="placeInto(left.id)"
          >
            <template #item="{ element }">
              <span class="sa-match__token sa-match__token--placed">{{ element.text }}</span>
            </template>
          </draggable>
        </li>
      </ul>

      <!-- RIGHT column: pool of draggable / selectable tokens -->
      <draggable
        v-model="pool"
        item-key="id"
        tag="ul"
        class="sa-match__pool"
        group="match"
        :disabled="locked"
        :animation="0"
        :aria-label="t('q.match.pool')"
      >
        <template #item="{ element }">
          <li>
            <button
              type="button"
              class="sa-match__token"
              :class="{ 'sa-match__token--picked': picked?.id === element.id }"
              :aria-pressed="picked?.id === element.id"
              :disabled="locked"
              @click="togglePick(element)"
            >
              {{ element.text }}
            </button>
          </li>
        </template>
      </draggable>
    </div>

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
.sa-q__hint {
  color: var(--color-ink-soft);
  font-size: 0.9rem;
  margin: 0;
}
.sa-match {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1rem;
}
.sa-match__left,
.sa-match__pool {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.sa-match__row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.sa-match__leftlabel {
  flex: 1;
  font-weight: 600;
}
.sa-match__slot {
  flex: 1;
  min-height: var(--tap-min);
  min-width: 6rem;
  display: flex;
  align-items: center;
  padding: 0.35rem 0.5rem;
  border: 2px dashed var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface-2);
  cursor: pointer;
}
.sa-match__slot--target {
  border-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 10%, var(--color-surface));
}
.sa-match__slot--filled {
  border-style: solid;
}
.sa-match__pool {
  padding: 0.5rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  min-height: var(--tap-min);
}
.sa-match__token {
  display: inline-flex;
  align-items: center;
  min-height: var(--tap-min);
  width: 100%;
  padding: 0.55rem 0.85rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
  color: var(--color-ink);
  font: inherit;
  cursor: grab;
  text-align: start;
}
.sa-match__token--picked {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.sa-match__token--placed {
  cursor: grab;
  background: color-mix(in srgb, var(--color-primary) 12%, var(--color-surface));
  border-color: var(--color-primary);
}
.sa-q__check {
  align-self: flex-start;
}
@media (min-width: 640px) {
  .sa-match {
    grid-template-columns: 1.4fr 1fr;
    align-items: start;
  }
}
</style>

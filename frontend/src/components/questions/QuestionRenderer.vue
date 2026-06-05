<script setup lang="ts">
/**
 * Maps an ItemPublic to the right interactive question component (exhaustive over all 8
 * item_types) and re-emits the normalized AnswerEvent. F3 views (TestRunner / LessonReader)
 * render <QuestionRenderer :item> and listen for @answer.
 */
import { computed, ref } from 'vue'

import FillBlankQuestion from '@/components/questions/FillBlankQuestion.vue'
import HotspotQuestion from '@/components/questions/HotspotQuestion.vue'
import MatchQuestion from '@/components/questions/MatchQuestion.vue'
import McqQuestion from '@/components/questions/McqQuestion.vue'
import NumericQuestion from '@/components/questions/NumericQuestion.vue'
import OrderQuestion from '@/components/questions/OrderQuestion.vue'
import ShortAnswerQuestion from '@/components/questions/ShortAnswerQuestion.vue'
import TrueFalseQuestion from '@/components/questions/TrueFalseQuestion.vue'
import type { AnswerEvent, ItemPublic, ItemType } from '@/types/question'
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

// Exhaustive mapping. The Record<ItemType, ...> type makes a missing case a compile error.
const COMPONENT: Record<ItemType, unknown> = {
  mcq: McqQuestion,
  true_false: TrueFalseQuestion,
  cloze: FillBlankQuestion,
  short_answer: ShortAnswerQuestion,
  numeric: NumericQuestion,
  match: MatchQuestion,
  order: OrderQuestion,
  hotspot: HotspotQuestion,
}

const resolved = computed(() => COMPONENT[props.item.item_type])

// Ref to the active question component so a "managed" consumer (the quiz) can drive a single
// external Check/Next button: it reads canSubmit (reactive) and calls submit().
const inner = ref<{ submit?: () => void; canSubmit?: boolean } | null>(null)
defineExpose({
  submit: () => inner.value?.submit?.(),
  canSubmit: computed(() => Boolean(inner.value?.canSubmit)),
})

function onAnswer(payload: AnswerEvent) {
  emit('answer', payload)
}
</script>

<template>
  <component
    :is="resolved"
    v-if="resolved"
    ref="inner"
    :item="item"
    :disabled="disabled"
    :feedback="feedback"
    :sound="sound"
    :managed="managed"
    @answer="onAnswer"
  />
  <div v-else class="sa-card sa-q-unknown" role="alert">
    {{ item.item_type }}
  </div>
</template>

<style scoped>
.sa-q-unknown {
  padding: 1rem;
  color: var(--color-ink-soft);
}
</style>

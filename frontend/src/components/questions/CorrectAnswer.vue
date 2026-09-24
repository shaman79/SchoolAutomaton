<script setup lang="ts">
/**
 * After a wrong answer, show the right one straight away — immediate corrective feedback, so the child
 * doesn't have to wait for the review screen to learn what was expected. Renders nothing otherwise.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatAnswer } from '@/lib/answers'
import type { ItemPublic } from '@/types/question'
import type { GradeResult } from '@/types/session'

const props = defineProps<{ item: ItemPublic; feedback: GradeResult | null }>()
const { t } = useI18n()

const text = computed(() => {
  const f = props.feedback
  if (!f || f.is_correct || f.correct_answer == null) return ''
  return formatAnswer(props.item, f.correct_answer)
})
</script>

<template>
  <p v-if="text" class="sa-correct" role="status">
    <span class="sa-correct__label"><span aria-hidden="true">✓ </span>{{ t('review.correct_answer') }}:</span>
    {{ text }}
  </p>
</template>

<style scoped>
.sa-correct {
  margin: 0.6rem 0 0;
  padding: 0.6rem 0.8rem;
  border-radius: var(--radius-btn);
  border: 2px solid color-mix(in srgb, var(--color-mint) 55%, var(--color-line));
  background: color-mix(in srgb, var(--color-mint) 10%, var(--color-surface));
  font-weight: 600;
}
.sa-correct__label {
  color: color-mix(in srgb, var(--color-mint) 70%, black);
  margin-right: 0.25rem;
}
</style>

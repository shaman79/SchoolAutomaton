<script setup lang="ts">
/**
 * ReviewView — read-only walkthrough of a completed quiz. Resolves the quiz id (generation store,
 * else request status), fetches the learner's most recent attempt with answers revealed
 * (GET /quizzes/{id}/review), and lists every question with: the stem, the learner's answer, the
 * correct answer (when they differed), correct/incorrect status, and the explanation. Reusable
 * anytime from the results screen or "My lessons". Mobile-first, WCAG 2.2 AA.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import SaButton from '@/components/common/SaButton.vue'
import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { ApiError, api } from '@/lib/api'
import { useGenerationStore } from '@/stores/generation'
import type { ItemPublic } from '@/types/question'
import type { QuizReview } from '@/types/session'

const props = defineProps<{ sessionId: string }>()
const { t } = useI18n()
const gen = useGenerationStore()

const review = ref<QuizReview | null>(null)
const failed = ref(false)
const noAttempt = ref(false)
const loading = ref(true)

const accuracyPct = computed(() =>
  review.value ? Math.round(review.value.accuracy * 100) : 0,
)

/** Render a per-type submitted/correct value as readable text by mapping option ids → their labels. */
function formatValue(item: ItemPublic, value: unknown): string {
  if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) {
    return t('review.not_answered')
  }
  const p = item.payload
  switch (p.kind) {
    case 'mcq': {
      const ids = Array.isArray(value) ? value : [value]
      return ids.map((id) => p.options.find((o) => o.id === id)?.text ?? String(id)).join(', ')
    }
    case 'true_false':
      return value ? t('q.tf.true') : t('q.tf.false')
    case 'cloze': {
      const map = (value ?? {}) as Record<string, string>
      const filled = p.blanks.map((b) => map[b.id]).filter((v) => v != null && v !== '')
      return filled.length ? filled.join(', ') : t('review.not_answered')
    }
    case 'short_answer':
      return String(value)
    case 'numeric':
      return `${value as number}${p.unit ? ` ${p.unit}` : ''}`
    case 'match': {
      const pairs = (value as { left_id: string; right_id: string }[]) ?? []
      const left = (id: string) => p.left.find((s) => s.id === id)?.text ?? id
      const right = (id: string) => p.right.find((s) => s.id === id)?.text ?? id
      return pairs.map((pr) => `${left(pr.left_id)} → ${right(pr.right_id)}`).join('; ')
    }
    case 'order': {
      const ids = (value as string[]) ?? []
      return ids.map((id) => p.tokens.find((tk) => tk.id === id)?.text ?? id).join(' → ')
    }
    case 'hotspot': {
      const ids = Array.isArray(value) ? value : [value]
      return ids
        .map((id) => p.regions.find((r) => r.id === id)?.label ?? String(id))
        .join(', ')
    }
    default:
      return typeof value === 'string' ? value : JSON.stringify(value)
  }
}

onMounted(async () => {
  try {
    let id = gen.quizId
    if (!id) {
      const status = await api.getRequestStatus(props.sessionId)
      id = status.quiz_id
    }
    if (!id) {
      failed.value = true
      return
    }
    review.value = await api.getQuizReview(id)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) noAttempt.value = true
    else failed.value = true
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section v-if="review" class="sa-review">
    <header class="sa-review__header">
      <h1 class="sa-review__title">{{ review.title }}</h1>
      <p class="sa-review__score">
        {{ t('review.correct_of', { correct: review.correct_count, total: review.total }) }}
        · {{ accuracyPct }}%
      </p>
    </header>

    <ol class="sa-review__list">
      <li v-for="q in review.items" :key="q.ordinal" class="sa-card sa-review__q">
        <p class="sa-review__q-num">{{ t('review.question_n', { n: q.ordinal }) }}</p>
        <SafeContent :markdown="q.item.stem_markdown" prose class="sa-review__stem" />

        <dl class="sa-review__answers">
          <div class="sa-review__answer">
            <dt>{{ t('review.your_answer') }}</dt>
            <dd :class="{ 'sa-review__bad': !q.is_correct }">{{ formatValue(q.item, q.submitted_value) }}</dd>
          </div>
          <div v-if="!q.is_correct" class="sa-review__answer">
            <dt>{{ t('review.correct_answer') }}</dt>
            <dd class="sa-review__good">{{ formatValue(q.item, q.correct_answer) }}</dd>
          </div>
        </dl>

        <AnswerFeedback
          :correct="q.is_correct"
          :partial="q.partial_credit"
          :explanation="q.explanation"
        />
      </li>
    </ol>

    <div class="sa-review__actions safe-bottom">
      <SaButton variant="primary" size="lg" block icon="star" :to="{ name: 'stats' }">
        {{ t('results.view_progress') }}
      </SaButton>
      <SaButton variant="ghost" size="md" block icon="home" to="/">
        {{ t('results.again') }}
      </SaButton>
    </div>
  </section>

  <EmptyState
    v-else-if="noAttempt"
    icon="hint"
    :title="t('review.empty_title')"
    :description="t('review.empty_body')"
    announce
  >
    <SaButton variant="primary" to="/" icon="home">{{ t('common.back') }}</SaButton>
  </EmptyState>

  <EmptyState
    v-else-if="failed"
    icon="hint"
    :title="t('test.load_error_title')"
    :description="t('test.load_error_body')"
    announce
  >
    <SaButton variant="primary" to="/" icon="home">{{ t('common.back') }}</SaButton>
  </EmptyState>

  <div v-else-if="loading" class="sa-review__loading">
    <LoadingSpinner :size="40" :label="t('common.loading')" />
  </div>
</template>

<style scoped>
.sa-review {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.5rem 0 2rem;
}
.sa-review__header {
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.sa-review__title {
  font-size: clamp(1.4rem, 5vw, 1.9rem);
  font-weight: 800;
}
.sa-review__score {
  font-weight: 700;
  color: var(--color-ink-soft);
  font-variant-numeric: tabular-nums;
}
.sa-review__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  counter-reset: none;
}
.sa-review__q {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 1.1rem;
}
.sa-review__q-num {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-primary);
}
.sa-review__stem {
  margin: 0;
}
.sa-review__answers {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin: 0;
}
.sa-review__answer {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 0.5rem;
}
.sa-review__answer dt {
  font-weight: 700;
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-review__answer dd {
  margin: 0;
  font-weight: 600;
}
.sa-review__good {
  color: var(--color-mint, var(--color-primary-strong));
}
.sa-review__bad {
  color: var(--color-coral);
}
.sa-review__actions {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-top: 0.5rem;
}
.sa-review__loading {
  display: grid;
  place-items: center;
  padding: 4rem 0;
}
</style>

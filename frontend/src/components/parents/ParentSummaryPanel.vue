<script setup lang="ts">
/**
 * The calm parent overview of the last N days (a ParentSummary), in reading order: the period at a
 * glance (one compact row of numbers), practised topics judged in words ("confident / mostly / worth
 * practising" — never bare percentages or rankings), the mix-ups met, reviews waiting (only when some
 * are), and how to help (folded away — the same four tips every visit). Groups carry an icon +
 * heading, so meaning never rests on colour alone. Mobile-first.
 *
 * `remote` (a parent's own phone): no "start the review" button — it would start it there. With
 * `canAssign` a topic worth practising offers "Practise", which becomes a quiz task.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import SaIcon, { type IconName } from '@/components/common/SaIcon.vue'
import { subjectLabel } from '@/lib/format'
import type { ParentSummary, TopicProgress } from '@/types/session'

const props = withDefaults(
  defineProps<{ summary: ParentSummary; remote?: boolean; canAssign?: boolean }>(),
  { remote: false, canAssign: false },
)
const emit = defineEmits<{ (e: 'assign', topic: TopicProgress): void }>()

const { t, tm } = useI18n()

const GROUPS: { status: TopicProgress['status']; icon: IconName }[] = [
  { status: 'confident', icon: 'star' },
  { status: 'mostly', icon: 'check' },
  { status: 'practice', icon: 'hint' },
]

const groups = computed(() =>
  GROUPS.map((g) => ({
    ...g,
    topics: props.summary.topics.filter((topic) => topic.status === g.status),
  })).filter((g) => g.topics.length > 0),
)

const tips = computed<string[]>(() => {
  const raw = tm('parents.tips') as unknown
  return Array.isArray(raw) ? (raw as string[]) : []
})

const isEmpty = computed(() => props.summary.answers === 0 && props.summary.lessons === 0)
</script>

<template>
  <div class="sa-psum">
    <p v-if="isEmpty" class="sa-card sa-psum__note">{{ t('parents.empty', { n: summary.days }) }}</p>

    <template v-else>
      <!-- The period at a glance: one row of numbers (2 × 2 on a narrow phone) -->
      <dl class="sa-card sa-psum__stats">
        <div class="sa-psum__stat">
          <dt>{{ t('parents.active_days') }}</dt>
          <dd>{{ t('parents.of_days', { n: summary.active_days, total: summary.days }) }}</dd>
        </div>
        <div class="sa-psum__stat">
          <dt>{{ t('parents.lessons') }}</dt>
          <dd>{{ summary.lessons }}</dd>
        </div>
        <div class="sa-psum__stat">
          <dt>{{ t('parents.quizzes') }}</dt>
          <dd>{{ summary.quizzes_completed }}</dd>
        </div>
        <div class="sa-psum__stat">
          <dt>{{ t('parents.answers') }}</dt>
          <dd>{{ t('parents.answers_value', { n: summary.answers, correct: summary.correct }) }}</dd>
        </div>
      </dl>

      <!-- Topics judged in words -->
      <section v-if="groups.length" class="sa-card sa-psum__section">
        <h3 class="sa-psum__h3">{{ t('parents.topics_title') }}</h3>
        <div v-for="g in groups" :key="g.status" class="sa-psum__group" :data-status="g.status">
          <h4 class="sa-psum__h4">
            <SaIcon :name="g.icon" :size="18" />
            {{ t(`parents.status.${g.status}`) }}
          </h4>
          <ul class="sa-psum__list">
            <li v-for="topic in g.topics" :key="topic.concept_id" class="sa-psum__topic-row">
              <span class="sa-psum__topic-text">
                <span class="sa-psum__topic">{{ topic.title }}</span>
                <span class="sa-psum__meta">
                  {{ subjectLabel(topic.subject) }} ·
                  {{ t('parents.topic_answers', { correct: topic.correct, n: topic.answers }) }}
                </span>
              </span>
              <SaButton
                v-if="canAssign && topic.status === 'practice'"
                variant="ghost"
                size="sm"
                icon="sparkle"
                class="sa-psum__assign"
                :aria-label="`${t('parent.practise')}: ${topic.title}`"
                @click="emit('assign', topic)"
              >
                {{ t('parent.practise') }}
              </SaButton>
            </li>
          </ul>
        </div>
      </section>

      <!-- Wrong ideas met in the period -->
      <section v-if="summary.misconceptions.length" class="sa-card sa-psum__section">
        <h3 class="sa-psum__h3">{{ t('parents.misconceptions_title') }}</h3>
        <p class="sa-psum__meta">{{ t('parents.misconceptions_hint') }}</p>
        <ul class="sa-psum__list sa-psum__list--plain">
          <li v-for="m in summary.misconceptions" :key="m">{{ m }}</li>
        </ul>
      </section>
    </template>

    <!-- Reviews: only when some are waiting (otherwise there is nothing to do or say) -->
    <section v-if="summary.due_reviews > 0" class="sa-card sa-psum__section sa-psum__reviews">
      <h3 class="sa-psum__h3">{{ t('parents.reviews_title') }}</h3>
      <p>
        {{ t('daily.cta_count', { n: summary.due_reviews }, summary.due_reviews) }}.
        {{ t('parents.reviews_hint') }}
      </p>
      <SaButton v-if="!remote" variant="primary" block :to="{ name: 'daily' }">{{ t('daily.cta') }}</SaButton>
    </section>

    <!-- How to help: the same tips every time, so folded away -->
    <details class="sa-card sa-psum__tips">
      <summary class="sa-psum__summary">
        <SaIcon name="hint" :size="18" />
        <span>{{ t('parents.tips_title') }}</span>
      </summary>
      <ul class="sa-psum__list sa-psum__list--plain">
        <li v-for="(tip, i) in tips" :key="i">{{ tip }}</li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.sa-psum {
  container: sa-psum / inline-size;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.sa-psum__note {
  margin: 0;
  padding: 1.25rem 1.1rem;
  text-align: center;
  line-height: 1.5;
  color: var(--color-ink-soft);
}
/* One card of numbers: 2 × 2 on a phone, a single row once there is room. */
.sa-psum__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.9rem 0.75rem;
  margin: 0;
  padding: 0.9rem 1rem;
}
@container sa-psum (min-width: 34rem) {
  .sa-psum__stats {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.sa-psum__stat {
  display: flex;
  flex-direction: column-reverse; /* the number reads first, its label below */
  justify-content: flex-end;
  gap: 0.1rem;
  min-width: 0;
}
.sa-psum__stat dt {
  font-size: 0.8rem;
  line-height: 1.3;
  color: var(--color-ink-soft);
}
.sa-psum__stat dd {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 800;
  line-height: 1.25;
}
.sa-psum__section {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 1rem 1.1rem;
}
.sa-psum__section p {
  margin: 0;
  line-height: 1.5;
}
.sa-psum__h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 800;
}
.sa-psum__h4 {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0.35rem 0 0.25rem;
  font-size: 0.95rem;
  font-weight: 700;
}
/* A quiet accent rail per group; the icon + heading carry the meaning (never colour alone). */
.sa-psum__group {
  border-left: 4px solid var(--color-line);
  padding-left: 0.75rem;
}
.sa-psum__group[data-status='confident'] {
  border-left-color: var(--color-mint);
}
.sa-psum__group[data-status='practice'] {
  border-left-color: var(--color-sun);
}
.sa-psum__list {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-psum__list--plain {
  padding-left: 1.2rem;
  list-style: disc;
  line-height: 1.5;
}
.sa-psum__list--plain li {
  display: list-item;
}
/* Topic text, then (on a parent's phone) "Practise" beside it, or below on a narrow screen. */
.sa-psum__topic-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem 0.75rem;
}
.sa-psum__topic-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1 1 11rem;
}
.sa-psum__topic {
  font-weight: 600;
  overflow-wrap: break-word;
}
.sa-psum__assign {
  flex: 0 0 auto;
}
.sa-psum__meta {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-psum__reviews {
  border: 2px solid color-mix(in srgb, var(--color-sky) 45%, var(--color-line));
}
.sa-psum__tips {
  padding: 0 1.1rem;
}
.sa-psum__tips[open] {
  padding-bottom: 1rem;
}
.sa-psum__summary {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-height: var(--tap-min);
  padding: 0.35rem 0;
  font-weight: 700;
  cursor: pointer;
  list-style: none;
}
.sa-psum__summary::-webkit-details-marker {
  display: none;
}
.sa-psum__summary::after {
  content: '';
  margin-left: auto;
  width: 0.55rem;
  height: 0.55rem;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(45deg);
  transition: transform 0.15s;
}
.sa-psum__tips[open] .sa-psum__summary::after {
  transform: rotate(-135deg);
}
.sa-psum__summary:focus-visible {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
  border-radius: 4px;
}
</style>

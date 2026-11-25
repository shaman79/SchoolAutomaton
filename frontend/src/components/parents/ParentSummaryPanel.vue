<script setup lang="ts">
/**
 * The calm parent overview of the last N days (a ParentSummary): the period at a glance, practised
 * topics judged in words ("confident / mostly / worth practising" — never bare percentages or
 * rankings), the mix-ups met (something to talk about), reviews waiting, and how to help. Groups carry
 * an icon + heading, so meaning never rests on colour alone. Mobile-first.
 *
 * Shown on the learner's own device (/parents) and on a parent's phone (/parent, `remote`): there the
 * "start the review" button is left out (it would start it on the parent's phone), and with
 * `canAssign` a topic worth practising offers "Give as a task".
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

function assignable(topic: TopicProgress): boolean {
  return props.canAssign && topic.status !== 'confident'
}
</script>

<template>
  <div class="sa-psum">
    <div v-if="isEmpty" class="sa-card sa-psum__note">
      <p>{{ t('parents.empty', { n: summary.days }) }}</p>
    </div>

    <template v-else>
      <!-- The period at a glance -->
      <dl class="sa-psum__tiles">
        <div class="sa-card sa-psum__tile">
          <dt>{{ t('parents.active_days') }}</dt>
          <dd>{{ t('parents.of_days', { n: summary.active_days, total: summary.days }) }}</dd>
        </div>
        <div class="sa-card sa-psum__tile">
          <dt>{{ t('parents.lessons') }}</dt>
          <dd>{{ summary.lessons }}</dd>
        </div>
        <div class="sa-card sa-psum__tile">
          <dt>{{ t('parents.quizzes') }}</dt>
          <dd>{{ summary.quizzes_completed }}</dd>
        </div>
        <div class="sa-card sa-psum__tile">
          <dt>{{ t('parents.answers') }}</dt>
          <dd>{{ t('parents.answers_value', { n: summary.answers, correct: summary.correct }) }}</dd>
        </div>
      </dl>

      <!-- Topics judged in words -->
      <section v-if="groups.length" class="sa-card sa-psum__section">
        <h2 class="sa-psum__h2">{{ t('parents.topics_title') }}</h2>
        <div v-for="g in groups" :key="g.status" class="sa-psum__group" :data-status="g.status">
          <h3 class="sa-psum__h3">
            <SaIcon :name="g.icon" :size="20" />
            {{ t(`parents.status.${g.status}`) }}
          </h3>
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
                v-if="assignable(topic)"
                variant="subtle"
                size="sm"
                icon="sparkle"
                class="sa-psum__assign"
                :aria-label="`${t('parent.assign_topic')}: ${topic.title}`"
                @click="emit('assign', topic)"
              >
                {{ t('parent.assign_topic') }}
              </SaButton>
            </li>
          </ul>
        </div>
      </section>

      <!-- Wrong ideas met in the period -->
      <section v-if="summary.misconceptions.length" class="sa-card sa-psum__section">
        <h2 class="sa-psum__h2">{{ t('parents.misconceptions_title') }}</h2>
        <p class="sa-psum__hint">{{ t('parents.misconceptions_hint') }}</p>
        <ul class="sa-psum__list sa-psum__list--plain">
          <li v-for="m in summary.misconceptions" :key="m">{{ m }}</li>
        </ul>
      </section>
    </template>

    <!-- Spaced repetition waiting -->
    <section class="sa-card sa-psum__section">
      <h2 class="sa-psum__h2">{{ t('parents.reviews_title') }}</h2>
      <p v-if="summary.due_reviews > 0">
        {{ t('daily.cta_count', { n: summary.due_reviews }, summary.due_reviews) }}.
        {{ t('parents.reviews_hint') }}
      </p>
      <p v-else>{{ t('parents.reviews_none') }}</p>
      <SaButton
        v-if="summary.due_reviews > 0 && !remote"
        variant="primary"
        block
        :to="{ name: 'daily' }"
      >
        {{ t('daily.cta') }}
      </SaButton>
    </section>

    <!-- How to help -->
    <section class="sa-card sa-psum__section">
      <h2 class="sa-psum__h2">{{ t('parents.tips_title') }}</h2>
      <ul class="sa-psum__list sa-psum__list--plain">
        <li v-for="(tip, i) in tips" :key="i">{{ tip }}</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.sa-psum {
  container: sa-psum / inline-size;
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
}
.sa-psum__note {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 1.5rem 1.1rem;
  text-align: center;
  color: var(--color-ink-soft);
}
/* Two tiles a row while each gets ~7rem; one a row below that (big text on a phone overflowed). */
.sa-psum__tiles {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.75rem;
  margin: 0;
}
@container sa-psum (min-width: 15rem) {
  .sa-psum__tiles {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@container sa-psum (min-width: 36rem) {
  .sa-psum__tiles {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.sa-psum__tile {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.9rem;
}
.sa-psum__tile dt {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-psum__tile dd {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 800;
}
.sa-psum__section {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 1.1rem;
}
.sa-psum__h2 {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0;
}
.sa-psum__h3 {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 1rem;
  font-weight: 700;
  margin: 0.4rem 0 0.3rem;
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
}
.sa-psum__list--plain li {
  display: list-item;
}
/* Topic text, then (on a parent's phone) its "Give as a task" — beside it once there is room. */
.sa-psum__topic-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem 0.75rem;
}
.sa-psum__topic-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1 1 12rem;
}
.sa-psum__topic {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.sa-psum__assign {
  flex: 0 0 auto;
}
.sa-psum__meta,
.sa-psum__hint {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
  margin: 0;
}
</style>

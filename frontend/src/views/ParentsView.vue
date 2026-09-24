<script setup lang="ts">
/**
 * ParentsView — a calm weekly overview for parents (GET /profiles/me/summary). Practised topics are
 * judged in words ("confident / mostly / worth practising"), never as bare percentages or rankings,
 * and the wrong ideas met this week are listed so a parent knows what to talk about. Groups carry an
 * icon + heading, so meaning never rests on colour alone. Mobile-first.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import SaIcon, { type IconName } from '@/components/common/SaIcon.vue'
import { api } from '@/lib/api'
import { subjectLabel } from '@/lib/format'
import { useSessionStore } from '@/stores/session'
import type { ParentSummary, TopicProgress } from '@/types/session'

const { t, tm } = useI18n()
const session = useSessionStore()

const hasProfile = computed(() => !!session.resumeCode)
const summary = ref<ParentSummary | null>(null)
const loading = ref(false)
const failed = ref(false)

const GROUPS: { status: TopicProgress['status']; icon: IconName }[] = [
  { status: 'confident', icon: 'star' },
  { status: 'mostly', icon: 'check' },
  { status: 'practice', icon: 'hint' },
]

const groups = computed(() =>
  GROUPS.map((g) => ({
    ...g,
    topics: (summary.value?.topics ?? []).filter((topic) => topic.status === g.status),
  })).filter((g) => g.topics.length > 0),
)

const tips = computed<string[]>(() => {
  const raw = tm('parents.tips') as unknown
  return Array.isArray(raw) ? (raw as string[]) : []
})

const isEmpty = computed(
  () => !!summary.value && summary.value.answers === 0 && summary.value.lessons === 0,
)

async function load() {
  loading.value = true
  failed.value = false
  try {
    summary.value = await api.getSummary(7)
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (hasProfile.value) void load()
})
</script>

<template>
  <section class="sa-parents">
    <header class="sa-parents__head">
      <h1 class="sa-parents__title">{{ t('parents.title') }}</h1>
      <p class="sa-parents__sub">{{ t('parents.subtitle') }}</p>
    </header>

    <div v-if="!hasProfile" class="sa-card sa-parents__note">
      <p>{{ t('stats.no_profile') }}</p>
    </div>

    <p v-else-if="loading" class="sa-parents__note" role="status">{{ t('common.loading') }}</p>

    <div v-else-if="failed" class="sa-card sa-parents__note" role="alert">
      <p>{{ t('parents.load_error') }}</p>
      <SaButton variant="ghost" @click="load">{{ t('common.retry') }}</SaButton>
    </div>

    <template v-else-if="summary">
      <div v-if="isEmpty" class="sa-card sa-parents__note">
        <p>{{ t('parents.empty') }}</p>
      </div>

      <template v-else>
        <!-- The week at a glance -->
        <dl class="sa-parents__tiles">
          <div class="sa-card sa-parents__tile">
            <dt>{{ t('parents.active_days') }}</dt>
            <dd>{{ t('parents.of_days', { n: summary.active_days, total: summary.days }) }}</dd>
          </div>
          <div class="sa-card sa-parents__tile">
            <dt>{{ t('parents.lessons') }}</dt>
            <dd>{{ summary.lessons }}</dd>
          </div>
          <div class="sa-card sa-parents__tile">
            <dt>{{ t('parents.quizzes') }}</dt>
            <dd>{{ summary.quizzes_completed }}</dd>
          </div>
          <div class="sa-card sa-parents__tile">
            <dt>{{ t('parents.answers') }}</dt>
            <dd>{{ t('parents.answers_value', { n: summary.answers, correct: summary.correct }) }}</dd>
          </div>
        </dl>

        <!-- Topics judged in words -->
        <section v-if="groups.length" class="sa-card sa-parents__section">
          <h2 class="sa-parents__h2">{{ t('parents.topics_title') }}</h2>
          <div v-for="g in groups" :key="g.status" class="sa-parents__group" :data-status="g.status">
            <h3 class="sa-parents__h3">
              <SaIcon :name="g.icon" :size="20" />
              {{ t(`parents.status.${g.status}`) }}
            </h3>
            <ul class="sa-parents__list">
              <li v-for="topic in g.topics" :key="topic.concept_id">
                <span class="sa-parents__topic">{{ topic.title }}</span>
                <span class="sa-parents__meta">
                  {{ subjectLabel(topic.subject) }} ·
                  {{ t('parents.topic_answers', { correct: topic.correct, n: topic.answers }) }}
                </span>
              </li>
            </ul>
          </div>
        </section>

        <!-- Wrong ideas met this week -->
        <section v-if="summary.misconceptions.length" class="sa-card sa-parents__section">
          <h2 class="sa-parents__h2">{{ t('parents.misconceptions_title') }}</h2>
          <p class="sa-parents__hint">{{ t('parents.misconceptions_hint') }}</p>
          <ul class="sa-parents__list sa-parents__list--plain">
            <li v-for="m in summary.misconceptions" :key="m">{{ m }}</li>
          </ul>
        </section>
      </template>

      <!-- Spaced repetition waiting -->
      <section class="sa-card sa-parents__section">
        <h2 class="sa-parents__h2">{{ t('parents.reviews_title') }}</h2>
        <p v-if="summary.due_reviews > 0">
          {{ t('daily.cta_count', { n: summary.due_reviews }, summary.due_reviews) }}.
          {{ t('parents.reviews_hint') }}
        </p>
        <p v-else>{{ t('parents.reviews_none') }}</p>
        <SaButton v-if="summary.due_reviews > 0" variant="primary" block :to="{ name: 'daily' }">
          {{ t('daily.cta') }}
        </SaButton>
      </section>

      <!-- How to help -->
      <section class="sa-card sa-parents__section">
        <h2 class="sa-parents__h2">{{ t('parents.tips_title') }}</h2>
        <ul class="sa-parents__list sa-parents__list--plain">
          <li v-for="(tip, i) in tips" :key="i">{{ tip }}</li>
        </ul>
      </section>
    </template>
  </section>
</template>

<style scoped>
.sa-parents {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.5rem 0 2rem;
}
.sa-parents__head {
  text-align: center;
}
.sa-parents__title {
  font-size: 1.5rem;
  font-weight: 800;
}
.sa-parents__sub {
  margin: 0.25rem 0 0;
  color: var(--color-ink-soft);
}
.sa-parents__note {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 1.5rem 1.1rem;
  text-align: center;
  color: var(--color-ink-soft);
}
.sa-parents__tiles {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin: 0;
}
.sa-parents__tile {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.9rem;
}
.sa-parents__tile dt {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-parents__tile dd {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 800;
}
.sa-parents__section {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 1.1rem;
}
.sa-parents__h2 {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0;
}
.sa-parents__h3 {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 1rem;
  font-weight: 700;
  margin: 0.4rem 0 0.3rem;
}
/* A quiet accent rail per group; the icon + heading carry the meaning (never colour alone). */
.sa-parents__group {
  border-left: 4px solid var(--color-line);
  padding-left: 0.75rem;
}
.sa-parents__group[data-status='confident'] {
  border-left-color: var(--color-mint);
}
.sa-parents__group[data-status='practice'] {
  border-left-color: var(--color-sun);
}
.sa-parents__list {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-parents__list li {
  display: flex;
  flex-direction: column;
}
.sa-parents__list--plain {
  padding-left: 1.2rem;
  list-style: disc;
}
.sa-parents__list--plain li {
  display: list-item;
}
.sa-parents__topic {
  font-weight: 600;
}
.sa-parents__meta,
.sa-parents__hint {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
  margin: 0;
}
@media (min-width: 640px) {
  .sa-parents__tiles {
    grid-template-columns: repeat(4, 1fr);
  }
}
</style>

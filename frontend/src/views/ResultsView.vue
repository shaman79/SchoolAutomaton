<script setup lang="ts">
/**
 * ResultsView — the celebratory end-of-quiz screen. Reads the ResultsSummary the test store captured
 * from POST /attempts/{id}/complete (score, accuracy, XP, best combo, new badges, mastery changes)
 * and the live gamification snapshot (streak, level). Growth-mindset framed, reduced-motion aware.
 *
 * It also closes the loop: a primary CTA into the full progress screen, and a "more like this" strip
 * of existing lessons/quizzes to reuse next — surfaced more insistently when the score was sub-par.
 * Tolerant of a missing summary (e.g. a hard refresh resets the store): it still shows progress + picks.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import SuggestionsStrip from '@/components/common/SuggestionsStrip.vue'
import StreakFlame from '@/components/gamification/StreakFlame.vue'
import { useCelebration } from '@/composables/useCelebration'
import { api } from '@/lib/api'
import { useSessionStore } from '@/stores/session'
import { useTestStore } from '@/stores/test'
import type { ResultsSummary } from '@/components/gamification/types'
import type { LearningSessionSummary } from '@/types/session'

const props = defineProps<{ sessionId: string }>()
const { t } = useI18n()
const test = useTestStore()
const session = useSessionStore()
const { celebrateLevelUp } = useCelebration()

const summary = computed<ResultsSummary | null>(() => (test.summary as ResultsSummary | null) ?? null)

const accuracyPct = computed(() =>
  summary.value ? Math.round(summary.value.accuracy * 100) : null,
)
// "Sub-par" → surface similar content as a friendly second chance rather than a celebration.
const subPar = computed(() => summary.value != null && summary.value.accuracy < 0.6)

const newBadges = computed(() => summary.value?.new_badges ?? [])
// Only genuine gains (the backend already restricts mastery_changes to concepts answered correctly
// with positive movement; this drops any flat/rounding-equal entries defensively).
const masteryGains = computed(() =>
  (summary.value?.mastery_changes ?? []).filter((m) => m.after > m.before),
)

const streak = computed(() => session.gamification?.streak ?? null)

const headerRef = ref<HTMLElement | null>(null)

const suggestions = ref<LearningSessionSummary[]>([])

onMounted(async () => {
  // Make sure streak/level are current even on a direct visit.
  if (!session.gamification) {
    try {
      await session.refreshGamification()
    } catch {
      /* anonymous-only surface; fine to show without it */
    }
  }
  // A calm celebration when they did well (not on a sub-par run).
  if (summary.value && summary.value.accuracy >= 0.8) {
    void celebrateLevelUp(headerRef.value)
  }
  try {
    suggestions.value = await api.getRecommendations({ requestId: props.sessionId, limit: 4 })
  } catch {
    /* recommendations are best-effort */
  }
})
</script>

<template>
  <section class="sa-results">
    <header ref="headerRef" class="sa-results__header">
      <span class="sa-results__crown" aria-hidden="true">
        <SaIcon name="trophy" :size="40" />
      </span>
      <h1 class="sa-results__title">{{ t('results.title') }}</h1>
    </header>

    <!-- Headline stats -->
    <div v-if="summary" class="sa-results__stats">
      <div class="sa-card sa-stat">
        <span class="sa-stat__value">{{ summary.score }}<span class="sa-stat__sub">/{{ summary.max_score }}</span></span>
        <span class="sa-stat__label">{{ t('results.score') }}</span>
      </div>
      <div class="sa-card sa-stat">
        <span class="sa-stat__value">{{ accuracyPct }}<span class="sa-stat__sub">%</span></span>
        <span class="sa-stat__label">{{ t('results.accuracy') }}</span>
      </div>
      <div class="sa-card sa-stat">
        <span class="sa-stat__value">+{{ summary.xp_awarded }}</span>
        <span class="sa-stat__label">{{ t('results.xp_earned') }}</span>
      </div>
      <div v-if="summary.combo_max > 1" class="sa-card sa-stat">
        <span class="sa-stat__value">×{{ summary.combo_max }}</span>
        <span class="sa-stat__label">{{ t('gamification.combo_max') }}</span>
      </div>
    </div>

    <!-- Streak + new badges -->
    <div v-if="streak || newBadges.length" class="sa-results__row">
      <div v-if="streak" class="sa-card sa-results__streak">
        <StreakFlame :streak="streak" size="lg" />
      </div>
      <div v-if="newBadges.length" class="sa-card sa-results__badges">
        <h2 class="sa-results__h2">{{ t('results.new_badges') }}</h2>
        <ul class="sa-results__badge-list">
          <li v-for="b in newBadges" :key="b.code" class="sa-results__badge">
            <SaIcon name="trophy" :size="18" aria-hidden="true" />
            <span>{{ b.title }}</span>
          </li>
        </ul>
      </div>
    </div>

    <!-- What grew (mastery) -->
    <div v-if="masteryGains.length" class="sa-card sa-results__growth">
      <h2 class="sa-results__h2">{{ t('results.growth') }}</h2>
      <ul class="sa-results__growth-list">
        <li v-for="m in masteryGains" :key="m.concept_id" class="sa-results__growth-item">
          <span class="sa-results__growth-name">{{ m.name }}</span>
          <!-- the GAIN this attempt (the section is "What grew"), not just the absolute level -->
          <span class="sa-results__growth-delta">+{{ Math.max(0, Math.round((m.after - m.before) * 100)) }}%</span>
          <span class="sa-results__growth-bar" aria-hidden="true">
            <span class="sa-results__growth-fill" :style="{ width: `${Math.round(m.after * 100)}%` }" />
          </span>
        </li>
      </ul>
    </div>

    <!-- More like this (reuse) -->
    <SuggestionsStrip
      :items="suggestions"
      :title="t('results.similar')"
      :hint="subPar ? t('results.subpar') : null"
    />

    <!-- Actions -->
    <div class="sa-results__actions safe-bottom">
      <SaButton variant="primary" size="lg" block icon="star" :to="{ name: 'stats' }">
        {{ t('results.view_progress') }}
      </SaButton>
      <SaButton variant="ghost" size="md" block icon="books" :to="{ name: 'review', params: { sessionId } }">
        {{ t('results.review') }}
      </SaButton>
      <SaButton variant="ghost" size="md" block icon="home" to="/">
        {{ t('results.again') }}
      </SaButton>
    </div>
  </section>
</template>

<style scoped>
.sa-results {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.5rem 0 2rem;
}
.sa-results__header {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  text-align: center;
}
.sa-results__crown {
  display: grid;
  place-items: center;
  width: 4rem;
  height: 4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-sun) 22%, var(--color-surface));
  color: var(--color-sun);
}
.sa-results__title {
  font-size: clamp(1.6rem, 6vw, 2.1rem);
  font-weight: 800;
}
.sa-results__stats {
  display: grid;
  /* 3-up so the common Score/Accuracy/XP set is one balanced row (no orphaned 3rd card); the rare
     4-card combo run gets a tidy 2x2 at >=480px below. */
  grid-template-columns: repeat(3, 1fr);
  gap: 0.6rem;
}
.sa-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  padding: 0.9rem 0.6rem;
}
.sa-stat__value {
  font-size: 1.6rem;
  font-weight: 800;
  line-height: 1;
  color: var(--color-primary-strong);
  font-variant-numeric: tabular-nums;
}
.sa-stat__sub {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--color-ink-soft);
}
.sa-stat__label {
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--color-ink-soft);
}
.sa-results__row {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-results__streak {
  display: flex;
  align-items: center;
  padding: 0.9rem 1rem;
}
.sa-results__badges {
  padding: 0.9rem 1rem;
}
.sa-results__h2 {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0 0 0.5rem;
}
.sa-results__badge-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  list-style: none;
  margin: 0;
  padding: 0;
}
.sa-results__badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.3rem 0.6rem;
  border-radius: var(--radius-pill);
  font-weight: 700;
  font-size: 0.85rem;
  background: color-mix(in srgb, var(--color-sun) 18%, var(--color-surface));
  color: var(--color-ink);
}
.sa-results__growth {
  padding: 0.9rem 1rem;
}
.sa-results__growth-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  list-style: none;
  margin: 0;
  padding: 0;
}
.sa-results__growth-item {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 0.3rem 0.6rem;
}
.sa-results__growth-name {
  font-weight: 600;
  grid-column: 1 / 2;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-results__growth-delta {
  grid-column: 2 / 3;
  font-weight: 800;
  color: color-mix(in srgb, var(--color-mint) 80%, black);
  font-variant-numeric: tabular-nums;
}
.sa-results__growth-bar {
  grid-column: 1 / 3;
  height: 0.5rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
  overflow: hidden;
}
.sa-results__growth-fill {
  display: block;
  height: 100%;
  border-radius: var(--radius-pill);
  background: var(--color-mint, var(--color-primary));
}
.sa-results__actions {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-top: 0.5rem;
}
@media (min-width: 480px) {
  .sa-results__stats {
    grid-template-columns: repeat(4, 1fr);
  }
}
</style>

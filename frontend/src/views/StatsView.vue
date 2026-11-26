<script setup lang="ts">
/**
 * StatsView — "My progress": the learner's overall gamification + mastery picture, reachable from the
 * header cluster and as the primary CTA after finishing a quiz/lesson. Reads the live gamification
 * snapshot (level, XP, streak, daily goal, badges) and the knowledge tree (GET /profiles/me/tree).
 *
 * In reading order: the level, today (streak + daily goal), what is within reach next (the closest
 * badges and how to earn them), the badges earned so far (the full list folded away — a wall of
 * locked ones reads as "what you don't have"), and the knowledge garden. Self-referential progress
 * only (SDT) — never a comparison. Mobile-first, reduced-motion aware.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import DailyReviewCard from '@/components/common/DailyReviewCard.vue'
import SaButton from '@/components/common/SaButton.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import BadgeGrid from '@/components/gamification/BadgeGrid.vue'
import DailyGoalRing from '@/components/gamification/DailyGoalRing.vue'
import KnowledgeTree from '@/components/gamification/KnowledgeTree.vue'
import LevelBadge from '@/components/gamification/LevelBadge.vue'
import NextGoals from '@/components/gamification/NextGoals.vue'
import StreakFlame from '@/components/gamification/StreakFlame.vue'
import XpBar from '@/components/gamification/XpBar.vue'
import { api } from '@/lib/api'
import { useSessionStore } from '@/stores/session'
import type { KnowledgeTreeData } from '@/components/gamification/types'

const { t } = useI18n()
const session = useSessionStore()

const hasProfile = computed(() => !!session.resumeCode)
const gami = computed(() => session.gamification)
const badges = computed(() => gami.value?.badges ?? [])
// Earned ones, the newest first — the shelf.
const earned = computed(() =>
  badges.value
    .filter((b) => b.unlocked_at)
    .sort((a, b) => String(b.unlocked_at).localeCompare(String(a.unlocked_at))),
)

const tree = ref<KnowledgeTreeData | null>(null)
const treeLoading = ref(false)

onMounted(async () => {
  if (!hasProfile.value) return
  // Always re-read: the streak "as it stands now" changes with time. A snapshot already loaded shows
  // meanwhile; without one, wait for it.
  const fresh = session.refreshGamification().catch(() => {}) // best-effort
  if (!session.gamification) await fresh
  treeLoading.value = true
  try {
    tree.value = (await api.getTree()) as KnowledgeTreeData
  } catch {
    tree.value = null
  } finally {
    treeLoading.value = false
  }
})
</script>

<template>
  <section class="sa-stats">
    <h1 class="sa-stats__title">{{ t('stats.title') }}</h1>

    <!-- No profile yet -->
    <div v-if="!hasProfile" class="sa-card sa-stats__empty">
      <p>{{ t('stats.no_profile') }}</p>
      <SaButton variant="primary" to="/" icon="sparkle">{{ t('history.start_learning') }}</SaButton>
    </div>

    <template v-else>
      <!-- Hero: level medallion + progress to the next level. -->
      <div v-if="gami" class="sa-card sa-stats__hero">
        <LevelBadge :level="gami.level" size="lg" />
        <div class="sa-stats__hero-main">
          <p class="sa-stats__level-label">{{ t('gamification.level') }} {{ gami.level }}</p>
          <XpBar :snapshot="gami" hide-badge size="lg" />
        </div>
      </div>

      <!-- Today: streak + daily goal. -->
      <section v-if="gami" aria-labelledby="sa-stats-today">
        <h2 id="sa-stats-today" class="sa-stats__h2">{{ t('stats.today_title') }}</h2>
        <div class="sa-stats__tiles">
          <div class="sa-card sa-stats__tile">
            <StreakFlame :streak="gami.streak" size="lg" :show-label="false" />
            <span class="sa-stats__tile-label">
              {{
                gami.streak.current > 0
                  ? t('gamification.streak', gami.streak.current)
                  : t('gamification.streak_start')
              }}
            </span>
            <span v-if="gami.streak.longest > 0" class="sa-stats__tile-sub">
              {{ t('gamification.streak_longest', { n: gami.streak.longest }) }}
            </span>
          </div>
          <div class="sa-card sa-stats__tile">
            <DailyGoalRing :snapshot="gami" :size="92" />
          </div>
        </div>
        <DailyReviewCard class="mt-3" />
      </section>

      <!-- What can be earned next, and how. -->
      <section v-if="gami" class="sa-card sa-stats__section" aria-labelledby="sa-stats-next">
        <h2 id="sa-stats-next" class="sa-stats__h2">{{ t('gamification.goals_title') }}</h2>
        <NextGoals :badges="badges" />
      </section>

      <!-- Badges earned (a shelf); every badge, with how to earn it, folded away. -->
      <section v-if="gami" class="sa-card sa-stats__section" aria-labelledby="sa-stats-badges">
        <h2 id="sa-stats-badges" class="sa-stats__h2">
          {{ t('stats.badges_title') }}
          <span class="sa-stats__count">{{ t('gamification.badges_progress', { unlocked: earned.length, total: badges.length }) }}</span>
        </h2>
        <ul v-if="earned.length" class="sa-stats__shelf">
          <li v-for="b in earned" :key="b.code" class="sa-stats__medal">
            <span class="sa-stats__medal-icon" aria-hidden="true"><SaIcon name="trophy" :size="18" /></span>
            {{ b.title }}
          </li>
        </ul>
        <p v-else class="sa-stats__muted">{{ t('gamification.shelf_empty') }}</p>
        <details v-if="badges.length" class="sa-stats__all">
          <summary class="sa-stats__summary">{{ t('gamification.all_badges', { n: badges.length }) }}</summary>
          <BadgeGrid :badges="badges" :compact="false" :show-count="false" />
        </details>
      </section>

      <!-- Knowledge garden -->
      <section class="sa-card sa-stats__section" aria-labelledby="sa-stats-tree">
        <h2 id="sa-stats-tree" class="sa-stats__h2">{{ t('stats.tree_title') }}</h2>
        <KnowledgeTree :data="tree" :loading="treeLoading" />
      </section>

      <div class="sa-stats__actions safe-bottom">
        <SaButton variant="primary" size="lg" block icon="sparkle" to="/">
          {{ t('lesson.learn_more') }}
        </SaButton>
        <SaButton variant="ghost" block icon="users" :to="{ name: 'parent' }">
          {{ t('parent.title') }}
        </SaButton>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sa-stats {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  padding: 1.5rem 0 2rem;
}
.sa-stats__title {
  text-align: center;
  font-size: 1.5rem;
  font-weight: 800;
}
.sa-stats__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.9rem;
  padding: 1.75rem 1.1rem;
  text-align: center;
  color: var(--color-ink-soft);
}
.sa-stats__hero {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem;
}
.sa-stats__hero-main {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  min-width: 0;
  flex: 1;
}
.sa-stats__level-label {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 800;
}
.sa-stats__tiles {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}
.sa-stats__tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 1rem 0.75rem;
  text-align: center;
}
.sa-stats__tile-label {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--color-ink-soft);
}
.sa-stats__tile-sub {
  font-size: 0.78rem;
  color: var(--color-ink-soft);
}
.sa-stats__section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.1rem;
}
.sa-stats__h2 {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.25rem 0.75rem;
  font-size: 1.15rem;
  font-weight: 800;
  margin: 0 0 0.25rem;
}
.sa-stats__count {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-stats__muted {
  margin: 0;
  color: var(--color-ink-soft);
  line-height: 1.45;
}
/* Earned badges: a shelf of filled medals with their names. */
.sa-stats__shelf {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-stats__medal {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.3rem 0.8rem 0.3rem 0.3rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-sun) 16%, var(--color-surface));
  font-weight: 700;
}
.sa-stats__medal-icon {
  display: grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border-radius: var(--radius-pill);
  color: var(--color-on-primary);
  background: radial-gradient(120% 120% at 30% 20%, var(--color-sun), var(--color-accent) 70%, var(--color-primary));
}
.sa-stats__all {
  border-top: 1px solid var(--color-line);
}
.sa-stats__all[open] > :last-child {
  margin-top: 0.5rem;
}
.sa-stats__summary {
  display: flex;
  align-items: center;
  min-height: var(--tap-min);
  font-weight: 700;
  color: var(--color-ink-soft);
  cursor: pointer;
  list-style: none;
}
.sa-stats__summary::-webkit-details-marker {
  display: none;
}
.sa-stats__summary::after {
  content: '';
  margin-left: auto;
  margin-right: 0.5rem;
  width: 0.5rem;
  height: 0.5rem;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(45deg);
}
.sa-stats__all[open] .sa-stats__summary::after {
  transform: rotate(-135deg);
}
.sa-stats__summary:focus-visible {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
  border-radius: 4px;
}
.sa-stats__actions {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-top: 0.25rem;
}
</style>

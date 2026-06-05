<script setup lang="ts">
/**
 * StatsView — "My progress": the learner's overall gamification + mastery picture, reachable from the
 * header cluster and as the primary CTA after finishing a quiz/lesson. Reads the live gamification
 * snapshot (level, XP, streak, daily goal, badges) and the knowledge tree (GET /profiles/me/tree).
 * Self-referential progress only (SDT) — never a comparison. Mobile-first, reduced-motion aware.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import BadgeGrid from '@/components/gamification/BadgeGrid.vue'
import DailyGoalRing from '@/components/gamification/DailyGoalRing.vue'
import KnowledgeTree from '@/components/gamification/KnowledgeTree.vue'
import LevelBadge from '@/components/gamification/LevelBadge.vue'
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

const tree = ref<KnowledgeTreeData | null>(null)
const treeLoading = ref(false)

onMounted(async () => {
  if (!hasProfile.value) return
  try {
    if (!session.gamification) await session.refreshGamification()
  } catch {
    /* best-effort */
  }
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

      <!-- Streak + daily goal as two balanced tiles, under a section heading for consistent rhythm. -->
      <section v-if="gami">
        <h2 class="sa-stats__h2">{{ t('stats.today_title') }}</h2>
        <div class="sa-stats__tiles">
          <div class="sa-card sa-stats__tile">
            <StreakFlame :streak="gami.streak" size="lg" :show-label="false" />
            <span class="sa-stats__tile-label">
              {{ gami.streak.current > 0 ? t('gamification.streak') : t('gamification.streak_start') }}
            </span>
            <span v-if="gami.streak.longest > 0" class="sa-stats__tile-sub">
              {{ t('gamification.streak_longest', { n: gami.streak.longest }) }}
            </span>
          </div>
          <div class="sa-card sa-stats__tile">
            <DailyGoalRing :snapshot="gami" :size="92" />
          </div>
        </div>
      </section>

      <!-- Badges -->
      <section class="sa-card sa-stats__section">
        <h2 class="sa-stats__h2">{{ t('stats.badges_title') }}</h2>
        <BadgeGrid :badges="badges" />
      </section>

      <!-- Knowledge tree -->
      <section class="sa-card sa-stats__section">
        <h2 class="sa-stats__h2">{{ t('stats.tree_title') }}</h2>
        <KnowledgeTree :data="tree" :loading="treeLoading" />
      </section>

      <div class="sa-stats__actions safe-bottom">
        <SaButton variant="primary" size="lg" block icon="sparkle" to="/">
          {{ t('lesson.learn_more') }}
        </SaButton>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sa-stats {
  display: flex;
  flex-direction: column;
  gap: 1.35rem;
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
  padding: 1.4rem;
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
  padding: 1.15rem 0.75rem;
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
  padding: 1.1rem;
}
.sa-stats__h2 {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0 0 0.75rem;
}
.sa-stats__actions {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-top: 0.5rem;
}
</style>

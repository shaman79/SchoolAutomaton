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
      <!-- Level + XP + streak -->
      <div v-if="gami" class="sa-card sa-stats__hero">
        <div class="sa-stats__level">
          <LevelBadge :level="gami.level" size="md" />
          <div class="min-w-0 flex-1">
            <XpBar :snapshot="gami" hide-badge size="lg" />
          </div>
        </div>
        <div class="sa-stats__hero-row">
          <StreakFlame :streak="gami.streak" size="lg" />
          <DailyGoalRing :snapshot="gami" :size="78" />
        </div>
      </div>

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
        <SaButton variant="ghost" size="md" block icon="books" :to="{ name: 'history' }">
          {{ t('history.title') }}
        </SaButton>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sa-stats {
  display: flex;
  flex-direction: column;
  gap: 1rem;
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
  flex-direction: column;
  gap: 1rem;
  padding: 1.1rem;
}
.sa-stats__level {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}
.sa-stats__hero-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
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

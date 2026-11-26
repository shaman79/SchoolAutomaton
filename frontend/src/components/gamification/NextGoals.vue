<script setup lang="ts">
/**
 * "Within reach" — the badges not earned yet that are closest, each with HOW to earn it (its
 * description) and how far along the learner is. A wall of locked badges says "you don't have
 * these"; a short list of next steps says "here is what you can do next" (SDT competence). Closest
 * first (share of the way done), then the catalogue order, which starts with the easy ones.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import ProgressBar from '@/components/common/ProgressBar.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import type { BadgeInfo } from './types'

const props = withDefaults(defineProps<{ badges: BadgeInfo[]; limit?: number }>(), { limit: 3 })

const { t } = useI18n()

const share = (b: BadgeInfo) =>
  b.progress_denominator > 0 ? Math.min(1, b.progress_numerator / b.progress_denominator) : 0

const goals = computed(() =>
  props.badges
    .map((b, i) => ({ b, i }))
    .filter(({ b }) => !b.unlocked_at)
    .sort((x, y) => share(y.b) - share(x.b) || x.i - y.i)
    .slice(0, props.limit)
    .map(({ b }) => b),
)

function counted(b: BadgeInfo): boolean {
  return b.progress_denominator > 1
}
function left(b: BadgeInfo): number {
  return Math.max(0, b.progress_denominator - b.progress_numerator)
}
</script>

<template>
  <ul v-if="goals.length" class="sa-goals">
    <li v-for="b in goals" :key="b.code" class="sa-goals__item">
      <span class="sa-goals__medal" aria-hidden="true"><SaIcon name="trophy" :size="20" /></span>
      <div class="sa-goals__body">
        <p class="sa-goals__title">{{ b.title }}</p>
        <p v-if="b.description" class="sa-goals__how">{{ b.description }}</p>
        <div v-if="counted(b)" class="sa-goals__progress">
          <ProgressBar
            :value="Math.min(b.progress_numerator, b.progress_denominator)"
            :max="b.progress_denominator"
            tone="accent"
            size="sm"
            :label="b.title"
            :value-text="`${Math.min(b.progress_numerator, b.progress_denominator)} / ${b.progress_denominator}`"
          />
          <span class="sa-goals__left">{{ t('gamification.goal_left', { n: left(b) }, left(b)) }}</span>
        </div>
      </div>
    </li>
  </ul>
  <p v-else class="sa-goals__all">{{ t('gamification.goals_all_done') }}</p>
</template>

<style scoped>
.sa-goals {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-goals__item {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}
/* Not earned yet: an outlined medal (the earned ones are filled) — the words say which, too. */
.sa-goals__medal {
  display: grid;
  place-items: center;
  flex: none;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: var(--radius-pill);
  border: 2px dashed color-mix(in srgb, var(--color-accent) 60%, var(--color-line));
  color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 8%, var(--color-surface));
}
.sa-goals__body {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  flex: 1;
  min-width: 0;
}
.sa-goals__title {
  margin: 0;
  font-weight: 800;
}
.sa-goals__how {
  margin: 0;
  font-size: 0.88rem;
  line-height: 1.4;
  color: var(--color-ink-soft);
}
.sa-goals__progress {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.3rem;
}
.sa-goals__progress > :first-child {
  flex: 1;
  min-width: 0;
}
.sa-goals__left {
  flex: none;
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--color-ink-soft);
}
.sa-goals__all {
  margin: 0;
  color: var(--color-ink-soft);
}
</style>

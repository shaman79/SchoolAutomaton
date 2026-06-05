<script setup lang="ts">
/**
 * XP progress bar toward the next level. Competence-supporting (SDT): it always frames how close
 * you are to the next level, never how far behind. Reads an explicit `snapshot` prop or, when
 * omitted, falls back to the session store's gamification snapshot.
 *
 * The fill animates via ProgressBar (which itself honors reduced-motion); we add an optional
 * level-up celebration when the level prop changes upward — gated through useCelebration.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import LevelBadge from './LevelBadge.vue'
import type { GamificationSnapshot } from './types'
import ProgressBar from '@/components/common/ProgressBar.vue'
import { useCelebration } from '@/composables/useCelebration'
import { useSessionStore } from '@/stores/session'

const props = withDefaults(
  defineProps<{
    /** Explicit snapshot; if absent, reads the session store. */
    snapshot?: GamificationSnapshot | null
    /** Hide the leading level badge (e.g. when shown alongside one already). */
    hideBadge?: boolean
    size?: 'sm' | 'md' | 'lg'
    /** Celebrate when the level increases while mounted (header XP gains). */
    celebrateLevelUp?: boolean
  }>(),
  { snapshot: null, hideBadge: false, size: 'md', celebrateLevelUp: false },
)

const { t } = useI18n()
const session = useSessionStore()
const { celebrateLevelUp: fireLevelUp } = useCelebration()

const snap = computed<GamificationSnapshot | null>(() => props.snapshot ?? session.gamification)
const level = computed(() => snap.value?.level ?? 1)
const pct = computed(() => Math.round(snap.value?.level_progress_pct ?? 0))
const xpToNext = computed(() => snap.value?.xp_to_next ?? 0)

const valueText = computed(() =>
  xpToNext.value > 0
    ? t('gamification.xp_to_next', { n: xpToNext.value })
    : t('gamification.xp_max'),
)

const barEl = ref<HTMLElement | null>(null)

watch(level, (next, prev) => {
  if (props.celebrateLevelUp && prev != null && next > prev) {
    void fireLevelUp(barEl.value)
  }
})
</script>

<template>
  <div ref="barEl" class="flex items-center gap-3">
    <LevelBadge v-if="!hideBadge" :level="level" :size="size === 'lg' ? 'md' : 'sm'" />
    <div class="min-w-0 flex-1">
      <ProgressBar
        :value="pct"
        tone="primary"
        :size="size"
        :label="t('gamification.bar_label')"
        :value-text="valueText"
        :show-value="size !== 'sm'"
      />
    </div>
  </div>
</template>

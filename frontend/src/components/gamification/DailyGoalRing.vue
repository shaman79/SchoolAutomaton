<script setup lang="ts">
/**
 * Circular daily-goal ring: today's earned XP (daily_progress_xp) against the goal for the
 * profile's daily_goal tier. SVG ring (mobile-friendly, crisp at any size). The arc length encodes
 * progress; a centered "N / G XP" label + a checkmark on completion carry the meaning without relying
 * on color. Completing the goal can fire a small celebration (motion-gated) once.
 *
 * Goal→XP targets are a UI presentation choice (the backend caps new items, not XP); they live here.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { GamificationSnapshot } from './types'
import SaIcon from '@/components/common/SaIcon.vue'
import { useCelebration } from '@/composables/useCelebration'
import { useReducedMotion } from '@/composables/useReducedMotion'
import { useSessionStore } from '@/stores/session'

/** XP targets per daily-goal tier (presentation-only). */
const GOAL_XP: Record<string, number> = {
  casual: 30,
  regular: 60,
  serious: 120,
  intense: 200,
}

const props = withDefaults(
  defineProps<{
    snapshot?: GamificationSnapshot | null
    size?: number
    /** Celebrate the first time the goal is reached while mounted. */
    celebrateOnComplete?: boolean
  }>(),
  { snapshot: null, size: 88, celebrateOnComplete: false },
)

const { t } = useI18n()
const { reduced } = useReducedMotion()
const { celebrateBadge } = useCelebration()
const session = useSessionStore()

const snap = computed<GamificationSnapshot | null>(() => props.snapshot ?? session.gamification)
const earned = computed(() => Math.max(0, snap.value?.daily_progress_xp ?? 0))
const goal = computed(() => GOAL_XP[snap.value?.daily_goal ?? 'regular'] ?? GOAL_XP.regular)
const pct = computed(() => Math.min(100, Math.round((earned.value / goal.value) * 100)))
const complete = computed(() => earned.value >= goal.value)

// Ring geometry.
const stroke = computed(() => Math.max(6, Math.round(props.size * 0.1)))
const radius = computed(() => (props.size - stroke.value) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const dashOffset = computed(() => circumference.value * (1 - pct.value / 100))

const a11yLabel = computed(() =>
  t('gamification.daily_goal_a11y', { earned: earned.value, goal: goal.value }),
)

const ringEl = ref<HTMLElement | null>(null)
const fired = ref(false)
watch(complete, (now) => {
  if (now && props.celebrateOnComplete && !fired.value) {
    fired.value = true
    void celebrateBadge(ringEl.value)
  }
})
</script>

<template>
  <div
    ref="ringEl"
    class="sa-goal-ring inline-flex flex-col items-center gap-1"
    role="img"
    :aria-label="a11yLabel"
  >
    <!-- relative box sized to the SVG => the centered label overlays the ring exactly, regardless of
         the flex gap, the caption below, or any ancestor positioning. -->
    <div class="relative" :style="{ width: size + 'px', height: size + 'px' }">
      <svg
        :width="size"
        :height="size"
        :viewBox="`0 0 ${size} ${size}`"
        class="sa-goal-ring__svg -rotate-90"
        aria-hidden="true"
        focusable="false"
      >
        <circle
          :cx="size / 2"
          :cy="size / 2"
          :r="radius"
          fill="none"
          stroke="var(--color-surface-2)"
          :stroke-width="stroke"
        />
        <circle
          class="sa-goal-ring__arc"
          :cx="size / 2"
          :cy="size / 2"
          :r="radius"
          fill="none"
          :stroke="complete ? 'var(--color-mint)' : 'var(--color-primary)'"
          :stroke-width="stroke"
          stroke-linecap="round"
          :stroke-dasharray="circumference"
          :stroke-dashoffset="dashOffset"
          :class="{ 'sa-goal-ring__arc--static': reduced }"
        />
      </svg>
      <span
        class="sa-goal-ring__center pointer-events-none absolute inset-0 flex flex-col items-center justify-center leading-none"
        aria-hidden="true"
      >
        <SaIcon
          v-if="complete"
          name="check"
          :size="Math.round(size * 0.34)"
          class="text-[var(--color-mint)]"
        />
        <template v-else>
          <span class="font-extrabold tabular-nums" :style="{ fontSize: size * 0.24 + 'px' }">
            {{ earned }}
          </span>
          <span class="text-[var(--color-ink-soft)]" :style="{ fontSize: size * 0.13 + 'px' }">
            / {{ goal }}
          </span>
        </template>
      </span>
    </div>
    <span class="text-xs font-semibold text-[var(--color-ink-soft)]">
      {{ complete ? t('gamification.daily_goal_done') : t('gamification.daily_goal') }}
    </span>
  </div>
</template>

<style scoped>
.sa-goal-ring__arc {
  transition: stroke-dashoffset 0.7s cubic-bezier(0.22, 1, 0.36, 1), stroke 0.3s ease;
}
.sa-goal-ring__arc--static,
:root[data-reduced-motion='true'] .sa-goal-ring__arc {
  transition: none;
}
</style>

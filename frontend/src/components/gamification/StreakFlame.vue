<script setup lang="ts">
/**
 * Current streak indicator. Three visual states, all framed positively (SDT competence, never
 * loss-aversion pressure):
 *   - active   → warm flame (sun), "N day streak"
 *   - frozen   → calm sky-blue shielded flame, "Streak protected" (a freeze was spent; NOT broken)
 *   - none     → soft neutral, "Start a streak today" (invitation, never a scold)
 *
 * Meaning is carried by the number + label + an icon shape change, never color alone.
 * A gentle idle flicker animation runs only when motion is allowed.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { StreakInfo } from './types'
import { useReducedMotion } from '@/composables/useReducedMotion'

const props = withDefaults(
  defineProps<{
    streak: StreakInfo
    size?: 'sm' | 'md' | 'lg'
    /** Show the textual label beside the flame (off → icon + count only). */
    showLabel?: boolean
  }>(),
  { size: 'md', showLabel: true },
)

const { t } = useI18n()
const { reduced } = useReducedMotion()

const count = computed(() => props.streak.current)
const isFrozen = computed(() => props.streak.frozen)
const isActive = computed(() => count.value > 0 && !isFrozen.value)

const iconPx = computed(() => ({ sm: 18, md: 24, lg: 34 })[props.size])

const label = computed(() => {
  if (isFrozen.value) return t('gamification.streak_protected')
  if (count.value > 0) return t('gamification.streak_count', { count: count.value })
  return t('gamification.streak_start')
})

const a11yLabel = computed(() => {
  if (isFrozen.value) return t('gamification.streak_protected_a11y', { count: count.value })
  if (count.value > 0) return t('gamification.streak_count', { count: count.value })
  return t('gamification.streak_start')
})

const flicker = computed(() => isActive.value && !reduced.value)
</script>

<template>
  <span
    class="sa-streak inline-flex items-center gap-1.5 font-semibold"
    :class="{
      'sa-streak--active': isActive,
      'sa-streak--frozen': isFrozen,
      'sa-streak--none': !isActive && !isFrozen,
    }"
    role="img"
    :aria-label="a11yLabel"
  >
    <span
      class="sa-streak__icon inline-grid place-items-center"
      :class="{ 'sa-streak__icon--flicker': flicker }"
      aria-hidden="true"
    >
      <!-- Frozen: shielded flame (distinct shape, not just a recolor). -->
      <svg
        v-if="isFrozen"
        :width="iconPx"
        :height="iconPx"
        viewBox="0 0 24 24"
        fill="none"
        focusable="false"
      >
        <path
          d="M12 4c.6 1.9-.4 3-1.4 4C9.4 9.2 8.5 10.3 8.5 12a3.5 3.5 0 0 0 7 0c0-1.2-.5-2.2-1.2-3 .1.9-.2 1.6-.8 2 .3-1.8-.6-3.4-1.4-4.6C11.6 5.5 12 4.8 12 4Z"
          fill="currentColor"
        />
        <path
          d="M12 13v7m-3.2-5.3 6.4 3.6m0-3.6-6.4 3.6"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
        />
      </svg>
      <!-- Active / none: clean, standard flame (filled when the streak is live). -->
      <svg v-else :width="iconPx" :height="iconPx" viewBox="0 0 24 24" fill="none" focusable="false">
        <path
          d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2-1-3-1.1-2.1-.2-4 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.2.4-2.3 1-3a2.5 2.5 0 0 0 2.5 2.5Z"
          :fill="isActive ? 'currentColor' : 'none'"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linejoin="round"
        />
      </svg>
    </span>
    <span v-if="count > 0" class="sa-streak__count tabular-nums" aria-hidden="true">{{ count }}</span>
    <span v-if="showLabel" class="sa-streak__label text-sm" aria-hidden="true">{{ label }}</span>
  </span>
</template>

<style scoped>
.sa-streak--active {
  color: var(--color-sun);
}
.sa-streak--frozen {
  color: var(--color-sky);
}
.sa-streak--none {
  color: var(--color-ink-soft);
}
.sa-streak__count {
  font-weight: 800;
}
.sa-streak__icon--flicker {
  animation: sa-flame-flicker 2.2s ease-in-out infinite;
  transform-origin: 50% 80%;
}
@keyframes sa-flame-flicker {
  0%,
  100% {
    transform: scale(1) rotate(0deg);
    opacity: 1;
  }
  45% {
    transform: scale(1.07) rotate(-1.5deg);
    opacity: 0.92;
  }
  70% {
    transform: scale(0.97) rotate(1.5deg);
  }
}
:root[data-reduced-motion='true'] .sa-streak__icon--flicker {
  animation: none;
}
</style>

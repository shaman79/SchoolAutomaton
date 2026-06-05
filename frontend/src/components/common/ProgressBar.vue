<script setup lang="ts">
/**
 * Accessible progress bar (WCAG / ARIA role=progressbar). Used for XP, quiz
 * progress, generation progress, daily goals. Width animates unless reduced
 * motion is active. Color is paired with the aria value text so meaning is
 * never color-only.
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** Current value (defaults 0..100 unless min/max given). */
    value: number
    min?: number
    max?: number
    tone?: 'primary' | 'success' | 'streak' | 'accent'
    size?: 'sm' | 'md' | 'lg'
    /** Accessible label describing what is progressing. */
    label?: string
    /** Optional human-readable value text (e.g. "120 / 300 XP"). */
    valueText?: string
    /** Show the valueText inline above the bar. */
    showValue?: boolean
    /** Indeterminate (unknown progress) — animated shimmer. */
    indeterminate?: boolean
  }>(),
  { min: 0, max: 100, tone: 'primary', size: 'md' },
)

const pct = computed(() => {
  if (props.indeterminate) return 0
  const span = props.max - props.min || 1
  const raw = ((props.value - props.min) / span) * 100
  return Math.max(0, Math.min(100, Math.round(raw)))
})

const heightClass = computed(
  () => ({ sm: 'h-1.5', md: 'h-2.5', lg: 'h-4' })[props.size],
)
const toneVar = computed(
  () =>
    ({
      primary: 'var(--color-primary)',
      success: 'var(--color-mint)',
      streak: 'var(--color-sun)',
      accent: 'var(--color-accent)',
    })[props.tone],
)
</script>

<template>
  <div class="w-full">
    <div
      v-if="showValue && (valueText || label)"
      class="mb-1 flex items-baseline justify-between text-xs font-semibold text-[var(--color-ink-soft)]"
    >
      <span v-if="label">{{ label }}</span>
      <span v-if="valueText">{{ valueText }}</span>
    </div>
    <div
      class="sa-progress overflow-hidden rounded-[var(--radius-pill)] bg-[var(--color-surface-2)]"
      :class="heightClass"
      role="progressbar"
      :aria-valuemin="indeterminate ? undefined : min"
      :aria-valuemax="indeterminate ? undefined : max"
      :aria-valuenow="indeterminate ? undefined : value"
      :aria-valuetext="valueText || undefined"
      :aria-label="label || undefined"
    >
      <div
        class="sa-progress__fill h-full rounded-[var(--radius-pill)]"
        :class="{ 'sa-progress__fill--indeterminate': indeterminate }"
        :style="indeterminate ? { background: toneVar } : { width: pct + '%', background: toneVar }"
      />
    </div>
  </div>
</template>

<style scoped>
.sa-progress__fill {
  transition: width 0.5s cubic-bezier(0.22, 1, 0.36, 1);
}
.sa-progress__fill--indeterminate {
  width: 35%;
  animation: sa-indeterminate 1.2s ease-in-out infinite;
}
@keyframes sa-indeterminate {
  0% {
    transform: translateX(-110%);
  }
  100% {
    transform: translateX(330%);
  }
}
:root[data-reduced-motion='true'] .sa-progress__fill {
  transition: none;
}
:root[data-reduced-motion='true'] .sa-progress__fill--indeterminate {
  width: 100%;
  animation: none;
  opacity: 0.6;
}
</style>

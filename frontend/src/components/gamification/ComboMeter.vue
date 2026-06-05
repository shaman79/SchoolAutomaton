<script setup lang="ts">
/**
 * Session combo multiplier (in-test). The server caps the multiplier at 2.0 once 8 answers in a row
 * are first-try-correct (combo_multiplier in GradeResult). This is a low-pressure "bonus building"
 * meter — it grows when you're on a roll and quietly resets, never flashing a "you lost it!" penalty.
 *
 * Drive it with either the raw `multiplier` from the latest GradeResult, or a `streakCount` of
 * consecutive first-try-correct answers (we then map to the same cap). The fill shows progress
 * toward the 2.0x cap. When the multiplier increases we give a tiny pop (motion-gated).
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { useReducedMotion } from '@/composables/useReducedMotion'

const COMBO_CAP = 2.0
const COMBO_CAP_AT = 8 // consecutive first-try-correct to reach the cap (SPEC §7)

const props = withDefaults(
  defineProps<{
    /** Latest server multiplier (1.0 .. 2.0). Takes precedence over streakCount. */
    multiplier?: number | null
    /** Consecutive first-try-correct count, if the multiplier isn't handy. */
    streakCount?: number | null
    size?: 'sm' | 'md'
  }>(),
  { multiplier: null, streakCount: null, size: 'md' },
)

const { t } = useI18n()
const { reduced } = useReducedMotion()

const value = computed(() => {
  if (props.multiplier != null) return Math.max(1, Math.min(COMBO_CAP, props.multiplier))
  const n = props.streakCount ?? 0
  // Linear ramp 1.0 → 2.0 across COMBO_CAP_AT first-try-correct answers.
  return Math.max(1, Math.min(COMBO_CAP, 1 + (n / COMBO_CAP_AT) * (COMBO_CAP - 1)))
})

const active = computed(() => value.value > 1.001)
const atCap = computed(() => value.value >= COMBO_CAP - 0.001)
const fillPct = computed(() => Math.round(((value.value - 1) / (COMBO_CAP - 1)) * 100))
const display = computed(() => `${value.value.toFixed(1)}x`)

const popping = ref(false)
watch(value, (next, prev) => {
  if (next > prev && !reduced.value) {
    popping.value = true
    window.setTimeout(() => (popping.value = false), 280)
  }
})
</script>

<template>
  <div
    v-show="active"
    class="sa-combo inline-flex items-center gap-2"
    role="status"
    aria-live="polite"
    :aria-label="t('gamification.combo_a11y', { mult: display })"
  >
    <span
      class="sa-combo__badge inline-flex items-center gap-1 rounded-[var(--radius-pill)] px-2.5 py-1 font-extrabold tabular-nums"
      :class="{ 'sa-combo__badge--cap': atCap, 'sa-combo__badge--pop': popping }"
    >
      <span aria-hidden="true">⚡</span>
      <span aria-hidden="true">{{ display }}</span>
    </span>
    <span
      v-if="size !== 'sm'"
      class="sa-combo__track relative h-2 w-16 overflow-hidden rounded-[var(--radius-pill)]"
      aria-hidden="true"
    >
      <span class="sa-combo__fill block h-full" :style="{ width: fillPct + '%' }" />
    </span>
    <span v-if="atCap" class="text-xs font-semibold text-[var(--color-sun)]" aria-hidden="true">
      {{ t('gamification.combo_max') }}
    </span>
  </div>
</template>

<style scoped>
.sa-combo__badge {
  background: linear-gradient(180deg, var(--color-sun), color-mix(in srgb, var(--color-sun) 70%, var(--color-coral)));
  color: var(--color-ink);
}
.sa-combo__badge--cap {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-sun) 60%, transparent);
}
.sa-combo__track {
  background: var(--color-surface-2);
}
.sa-combo__fill {
  background: var(--color-sun);
  transition: width 0.4s cubic-bezier(0.22, 1, 0.36, 1);
}
.sa-combo__badge--pop {
  animation: sa-combo-pop 0.28s ease-out;
}
@keyframes sa-combo-pop {
  0% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.18);
  }
  100% {
    transform: scale(1);
  }
}
:root[data-reduced-motion='true'] .sa-combo__fill {
  transition: none;
}
:root[data-reduced-motion='true'] .sa-combo__badge--pop {
  animation: none;
}
</style>

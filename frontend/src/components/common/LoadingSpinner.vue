<script setup lang="ts">
/**
 * Reduced-motion-aware loading spinner. When motion is reduced it falls back to a
 * gently pulsing dot instead of a continuous spin. Decorative by default; pass
 * `label` to announce loading to assistive tech (role=status, aria-live polite).
 */
import { useReducedMotion } from '@/composables/useReducedMotion'

withDefaults(
  defineProps<{
    size?: number | string
    label?: string
  }>(),
  { size: 24 },
)

const { reduced } = useReducedMotion()
</script>

<template>
  <span
    class="sa-spinner"
    :class="{ 'sa-spinner--static': reduced }"
    :role="label ? 'status' : undefined"
    :aria-live="label ? 'polite' : undefined"
    :aria-hidden="label ? undefined : 'true'"
    :style="{ width: typeof size === 'number' ? size + 'px' : size, height: typeof size === 'number' ? size + 'px' : size }"
  >
    <svg viewBox="0 0 24 24" fill="none" class="block w-full h-full" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" stroke-opacity="0.2" />
      <path
        class="sa-spinner__arc"
        d="M12 3a9 9 0 0 1 9 9"
        stroke="currentColor"
        stroke-width="3"
        stroke-linecap="round"
      />
    </svg>
    <span v-if="label" class="sr-only">{{ label }}</span>
  </span>
</template>

<style scoped>
.sa-spinner {
  display: inline-block;
  color: var(--color-primary);
}
.sa-spinner svg {
  animation: sa-spin 0.8s linear infinite;
}
.sa-spinner--static svg,
:root[data-reduced-motion='true'] .sa-spinner svg {
  animation: sa-pulse 1.4s ease-in-out infinite;
}
.sa-spinner--static .sa-spinner__arc {
  /* show the full ring rather than a sweeping arc when static */
  d: path('M12 3a9 9 0 0 1 0 18 9 9 0 0 1 0-18');
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@keyframes sa-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes sa-pulse {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}
</style>

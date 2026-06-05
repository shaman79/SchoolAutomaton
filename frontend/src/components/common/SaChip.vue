<script setup lang="ts">
/**
 * Pill / chip built on the .sa-chip primitive. Used for tags, filters, example
 * prompts, and small status badges. Can render as a clickable button (with a
 * full >=44px tap area) or a static label. Tone uses BOTH color and an optional
 * icon so meaning is never conveyed by color alone (WCAG 1.4.1).
 */
import { computed } from 'vue'

import SaIcon, { type IconName } from './SaIcon.vue'

const props = withDefaults(
  defineProps<{
    tone?: 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info'
    icon?: IconName
    /** Render as a <button> (clickable filter/example). */
    clickable?: boolean
    /** Visual selected state (adds aria-pressed when clickable). */
    selected?: boolean
  }>(),
  { tone: 'neutral' },
)

const toneClass = computed(() => `sa-chip--${props.tone}`)
</script>

<template>
  <component
    :is="clickable ? 'button' : 'span'"
    :type="clickable ? 'button' : undefined"
    class="sa-chip"
    :class="[toneClass, { 'sa-chip--clickable': clickable, 'sa-chip--selected': selected }]"
    :aria-pressed="clickable ? String(!!selected) : undefined"
  >
    <SaIcon v-if="icon" :name="icon" :size="15" />
    <slot />
  </component>
</template>

<style scoped>
.sa-chip--clickable {
  cursor: pointer;
  /* Keep a comfortable touch slop while staying visually compact. */
  min-height: var(--tap-min);
  transition: transform 0.1s ease, background 0.12s ease;
}
@media (hover: hover) {
  .sa-chip--clickable:hover {
    background: var(--color-bg-tint);
  }
}
.sa-chip--selected {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}
.sa-chip--primary {
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-chip--success {
  background: color-mix(in srgb, var(--color-mint) 18%, var(--color-surface));
  color: var(--color-on-mint);
}
.sa-chip--warning {
  background: color-mix(in srgb, var(--color-sun) 26%, var(--color-surface));
  color: var(--color-ink);
}
.sa-chip--danger {
  background: color-mix(in srgb, var(--color-coral) 16%, var(--color-surface));
  color: var(--color-ink);
}
.sa-chip--info {
  background: color-mix(in srgb, var(--color-sky) 18%, var(--color-surface));
  color: var(--color-ink);
}
:root[data-reduced-motion='true'] .sa-chip--clickable {
  transition: none;
}
</style>

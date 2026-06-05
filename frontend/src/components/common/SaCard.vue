<script setup lang="ts">
/**
 * Surface container built on the .sa-card primitive. Optional title/subtitle header
 * (rendered with a semantic heading at the requested level for correct outline),
 * optional interactive/clickable affordance, and padding control.
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    /** Heading level for the title (keeps document outline sane). */
    headingLevel?: 2 | 3 | 4
    padding?: 'none' | 'sm' | 'md' | 'lg'
    /** Subtle elevation lift; use the `pop` shadow for emphasis. */
    elevated?: boolean
    interactive?: boolean
  }>(),
  { headingLevel: 3, padding: 'md' },
)

const padClass = computed(
  () =>
    ({ none: 'p-0', sm: 'p-3', md: 'p-4 sm:p-5', lg: 'p-5 sm:p-7' })[props.padding],
)
const headingTag = computed(() => `h${props.headingLevel}` as 'h2' | 'h3' | 'h4')
</script>

<template>
  <div
    class="sa-card"
    :class="[padClass, { 'sa-card--pop': elevated, 'sa-card--interactive': interactive }]"
  >
    <header v-if="title || $slots.header" class="mb-3 flex items-start justify-between gap-3">
      <div v-if="title">
        <component :is="headingTag" class="text-lg font-bold leading-tight">{{ title }}</component>
        <p v-if="subtitle" class="text-sm text-[var(--color-ink-soft)] mt-0.5">{{ subtitle }}</p>
      </div>
      <slot name="header" />
    </header>
    <slot />
    <footer v-if="$slots.footer" class="mt-4">
      <slot name="footer" />
    </footer>
  </div>
</template>

<style scoped>
.sa-card--pop {
  box-shadow: var(--shadow-pop);
}
.sa-card--interactive {
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
@media (hover: hover) {
  .sa-card--interactive:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-pop);
  }
}
:root[data-reduced-motion='true'] .sa-card--interactive:hover {
  transform: none;
}
</style>

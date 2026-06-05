<script setup lang="ts">
/**
 * Friendly empty / zero-data / error placeholder. Centered illustration (icon),
 * a heading, supportive copy, and an optional call-to-action slot. Growth-mindset
 * tone — never a dead end.
 */
import SaIcon, { type IconName } from './SaIcon.vue'

withDefaults(
  defineProps<{
    icon?: IconName
    title: string
    description?: string
    /** When true the title is announced politely (e.g. after an async load). */
    announce?: boolean
  }>(),
  { icon: 'sparkle' },
)
</script>

<template>
  <div
    class="flex flex-col items-center justify-center gap-3 px-4 py-10 text-center"
    :role="announce ? 'status' : undefined"
    :aria-live="announce ? 'polite' : undefined"
  >
    <span
      class="grid place-items-center rounded-full p-4 text-[var(--color-primary)]"
      style="background: var(--color-bg-tint)"
    >
      <SaIcon :name="icon" :size="34" />
    </span>
    <h2 class="text-xl font-bold">{{ title }}</h2>
    <p v-if="description" class="max-w-prose text-[var(--color-ink-soft)]">{{ description }}</p>
    <div v-if="$slots.default" class="mt-2 flex flex-wrap items-center justify-center gap-2">
      <slot />
    </div>
  </div>
</template>

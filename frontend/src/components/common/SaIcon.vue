<script setup lang="ts">
/**
 * Inline SVG icon set for SchoolAutomaton. All paths are authored at a 24x24 viewBox,
 * use `currentColor` so they inherit text color, and are decorative by default
 * (aria-hidden) unless a `title` is supplied (then they expose an accessible name).
 * Stroke-based, rounded — matches the friendly, playful design language.
 */
import { computed } from 'vue'

export type IconName =
  | 'home'
  | 'sparkle'
  | 'flame'
  | 'star'
  | 'check'
  | 'x'
  | 'hint'
  | 'back'
  | 'settings'
  | 'trophy'
  | 'lock'

const props = withDefaults(
  defineProps<{
    name: IconName
    /** px size; default inherits via 1em so it scales with font-size. */
    size?: number | string
    /** Accessible name. When omitted the icon is aria-hidden (decorative). */
    title?: string
  }>(),
  { size: '1em' },
)

// Path data keyed by icon name. `stroke` = stroked outline; `fill` = filled shape.
const ICONS: Record<IconName, { stroke?: string; fill?: string }> = {
  home: {
    stroke: 'M4 11.5 12 4l8 7.5M6 10v9a1 1 0 0 0 1 1h3v-5h4v5h3a1 1 0 0 0 1-1v-9',
  },
  sparkle: {
    stroke:
      'M12 3.5c.6 3.7 1.8 4.9 5.5 5.5-3.7.6-4.9 1.8-5.5 5.5-.6-3.7-1.8-4.9-5.5-5.5 3.7-.6 4.9-1.8 5.5-5.5ZM18.5 14c.3 1.6.8 2.1 2.4 2.4-1.6.3-2.1.8-2.4 2.4-.3-1.6-.8-2.1-2.4-2.4 1.6-.3 2.1-.8 2.4-2.4Z',
  },
  flame: {
    stroke:
      'M12 3c.8 2.6-.5 4-1.8 5.3C8.7 9.8 7.5 11.2 7.5 13.5a4.5 4.5 0 0 0 9 0c0-1.6-.7-2.9-1.6-4 .2 1.2-.3 2.2-1.1 2.6.4-2.4-.8-4.6-1.8-6.1C11.4 5 12 4 12 3Z',
  },
  star: {
    stroke:
      'M12 3.5 14.6 9l6 .6-4.5 4 1.3 5.9L12 16.6 6.6 19.5l1.3-5.9-4.5-4 6-.6L12 3.5Z',
  },
  check: { stroke: 'M5 12.5 10 17.5 19 7' },
  x: { stroke: 'M6 6l12 12M18 6 6 18' },
  hint: {
    stroke:
      'M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2H14.5c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z',
  },
  back: { stroke: 'M14.5 5.5 8 12l6.5 6.5' },
  settings: {
    stroke:
      'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM12 2.5l1.2 2.3 2.5-.6 1 2.4 2.3 1.2-.6 2.5.6 2.5-2.3 1.2-1 2.4-2.5-.6L12 21.5l-1.2-2.3-2.5.6-1-2.4-2.3-1.2.6-2.5-.6-2.5 2.3-1.2 1-2.4 2.5.6L12 2.5Z',
  },
  trophy: {
    stroke:
      'M7 4h10v4a5 5 0 0 1-10 0V4ZM7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3M10 13.5V16M14 13.5V16M8 20h8M9 16h6l.5 4h-7l.5-4Z',
  },
  lock: {
    stroke:
      'M7 10V8a5 5 0 0 1 10 0v2M5.5 10h13a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1ZM12 14v3',
  },
}

const icon = computed(() => ICONS[props.name])
const decorative = computed(() => !props.title)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    :role="decorative ? undefined : 'img'"
    :aria-hidden="decorative ? 'true' : undefined"
    :aria-label="title || undefined"
    focusable="false"
    class="sa-icon inline-block shrink-0 align-[-0.125em]"
  >
    <title v-if="title">{{ title }}</title>
    <path
      v-if="icon.stroke"
      :d="icon.stroke"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <path v-if="icon.fill" :d="icon.fill" fill="currentColor" />
  </svg>
</template>

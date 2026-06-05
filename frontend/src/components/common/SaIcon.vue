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
  | 'books'
  | 'share'

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
    // Heroicons "cog-6-tooth" outline — clean gear teeth + centre hole.
    stroke:
      'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.7 7.7 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.5 6.5 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.5 6.5 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a7.7 7.7 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
  },
  trophy: {
    stroke:
      'M7 4h10v4a5 5 0 0 1-10 0V4ZM7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3M10 13.5V16M14 13.5V16M8 20h8M9 16h6l.5 4h-7l.5-4Z',
  },
  lock: {
    stroke:
      'M7 10V8a5 5 0 0 1 10 0v2M5.5 10h13a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1ZM12 14v3',
  },
  books: {
    // Open book with a centre spine — "my lessons".
    stroke:
      'M12 6.5C10.5 5.4 8.4 5 6.3 5 5.2 5 4.2 5.1 3.5 5.4v12c.7-.3 1.7-.4 2.8-.4 2.1 0 4.2.4 5.7 1.5M12 6.5c1.5-1.1 3.6-1.5 5.7-1.5 1.1 0 2.1.1 2.8.4v12c-.7-.3-1.7-.4-2.8-.4-2.1 0-4.2.4-5.7 1.5M12 6.5V18',
  },
  share: {
    // Three nodes joined — the standard "share" glyph.
    stroke:
      'M18 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM6 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM18 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM8.2 10.8l7.6-4.6M8.2 13.2l7.6 4.6',
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

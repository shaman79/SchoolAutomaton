<script setup lang="ts">
/**
 * Renders a single (untrusted) math expression with KaTeX, sanitized. Display mode by
 * default (block, centered); inline mode for in-prose math. Output goes through DOMPurify
 * via renderMathString. KaTeX runs trust:false / bounded maxExpand.
 */
import { computed } from 'vue'

import { renderMathString } from '@/lib/safeContent'

const props = withDefaults(
  defineProps<{
    /** The TeX source (without surrounding $ delimiters). */
    tex: string
    /** Inline vs display (block, centered) rendering. */
    inline?: boolean
    /** Accessible label override; defaults to the raw TeX. */
    ariaLabel?: string | null
  }>(),
  { inline: false, ariaLabel: null },
)

const html = computed(() => renderMathString(props.tex, !props.inline))
const label = computed(() => props.ariaLabel ?? props.tex)
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- KaTeX output is sanitized in safeContent.ts -->
  <component
    :is="inline ? 'span' : 'div'"
    class="sa-math"
    :class="{ 'sa-math--block': !inline }"
    role="math"
    :aria-label="label"
    v-html="html"
  />
</template>

<style scoped>
.sa-math--block {
  margin: 0.5rem 0;
  overflow-x: auto;
  overflow-y: hidden;
  text-align: center;
}
.sa-math :deep(.katex) {
  font-size: 1.05em;
}
</style>

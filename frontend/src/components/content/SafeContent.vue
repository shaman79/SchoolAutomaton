<script setup lang="ts">
/**
 * The ONLY component allowed to bind v-html in the app. It accepts EITHER markdown OR svg
 * (untrusted LLM / Replicate output) and binds it to v-html ONLY after sanitizing through
 * lib/safeContent. Never pass raw strings to v-html anywhere else (SPEC §5 / security_model).
 */
import { computed } from 'vue'

import { renderMarkdown, renderSvg } from '@/lib/safeContent'

const props = withDefaults(
  defineProps<{
    /** Untrusted markdown (with $math$). Rendered + sanitized. */
    markdown?: string | null
    /** Untrusted SVG markup. Sanitized with the SVG profile (script/foreignObject/on* stripped). */
    svg?: string | null
    /** Tag to render into (block prose => div, inline => span). */
    tag?: string
    /** Adds the readable-measure prose class for long lesson prose. */
    prose?: boolean
  }>(),
  { markdown: null, svg: null, tag: 'div', prose: false },
)

const html = computed(() => {
  if (props.svg != null) return renderSvg(props.svg)
  if (props.markdown != null) return renderMarkdown(props.markdown)
  return ''
})

const isSvg = computed(() => props.svg != null)
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- content is sanitized in safeContent.ts -->
  <component
    :is="tag"
    class="sa-safe-content"
    :class="[{ 'prose-reading': prose }, isSvg ? 'sa-safe-svg' : 'sa-safe-md']"
    v-html="html"
  />
</template>

<style scoped>
/* Light, readable defaults for sanitized markdown; tokens keep it on-theme. */
.sa-safe-md :deep(p) {
  margin: 0 0 0.85em;
}
.sa-safe-md :deep(h1),
.sa-safe-md :deep(h2),
.sa-safe-md :deep(h3) {
  margin: 1.1em 0 0.5em;
}
.sa-safe-md :deep(ul),
.sa-safe-md :deep(ol) {
  margin: 0 0 0.85em;
  padding-inline-start: 1.4em;
}
.sa-safe-md :deep(li) {
  margin: 0.2em 0;
}
.sa-safe-md :deep(a) {
  color: var(--color-primary-strong);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.sa-safe-md :deep(code) {
  background: var(--color-surface-2);
  padding: 0.1em 0.35em;
  border-radius: 0.4rem;
  font-size: 0.92em;
}
.sa-safe-md :deep(pre) {
  background: var(--color-surface-2);
  padding: 0.85rem 1rem;
  border-radius: var(--radius-btn);
  overflow-x: auto;
}
.sa-safe-md :deep(blockquote) {
  margin: 0 0 0.85em;
  padding: 0.2em 0 0.2em 1em;
  border-inline-start: 4px solid var(--color-line);
  color: var(--color-ink-soft);
}
.sa-safe-md :deep(table) {
  border-collapse: collapse;
  width: 100%;
}
.sa-safe-md :deep(th),
.sa-safe-md :deep(td) {
  border: 1px solid var(--color-line);
  padding: 0.4rem 0.6rem;
  text-align: start;
}
.sa-safe-md :deep(.sa-math-error) {
  color: var(--color-coral);
}
/* Inline + responsive SVG figures recolor with currentColor for themes. */
.sa-safe-svg :deep(svg) {
  max-width: 100%;
  height: auto;
  display: block;
}
</style>

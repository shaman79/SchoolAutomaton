<script setup lang="ts">
/**
 * Renders an AssetRef (dual-coding visual). Render paths:
 *   0. status=pending => a placeholder (reserved aspect ratio + alt text) shown while the image is
 *      still being generated, so it NEVER blocks the lesson text from appearing. The store polls and
 *      swaps in the real asset when it's ready.
 *   1. asset_type=svg with svg_inline => sanitized inline SVG (accessible, themeable, translatable).
 *   2. otherwise => <img> from the immutable /assets/{hash} url, with alt + optional caption.
 * Aspect ratio is reserved from layout_slot so the page does not shift (CLS) while the
 * raster loads. <img> is safe (scripts disabled in img context); SVG is DOMPurified.
 */
import { computed } from 'vue'

import SafeContent from '@/components/content/SafeContent.vue'
import type { AssetRef } from '@/types/session'

const props = defineProps<{
  asset: AssetRef
  /** Optional priority hint for above-the-fold hero images. */
  eager?: boolean
}>()

const isPending = computed(() => props.asset.status === 'pending')

// layout_slot -> CSS aspect-ratio reserving space to avoid layout shift.
const ASPECT: Record<string, string> = {
  HERO: '16 / 9',
  INLINE_FIGURE: '4 / 3',
  QUIZ_THUMB: '1 / 1',
  PORTRAIT_CHARACTER: '3 / 4',
  FULL_BLEED_MOBILE: '9 / 16',
}

const aspect = computed(() => ASPECT[props.asset.layout_slot] ?? '4 / 3')

const isInlineSvg = computed(
  () => props.asset.asset_type === 'svg' && !!props.asset.svg_inline,
)

const altText = computed(() => props.asset.alt_text || props.asset.caption || '')
</script>

<template>
  <figure class="sa-asset" :class="`sa-asset--${asset.layout_slot.toLowerCase()}`">
    <div class="sa-asset__frame" :style="{ aspectRatio: aspect }">
      <!-- Pending: the image is still generating. Reserve the space + show the alt text so the part
           reads now and the picture fills in when ready (the store polls + swaps it). -->
      <div
        v-if="isPending"
        class="sa-asset__placeholder"
        :role="altText ? 'img' : undefined"
        :aria-label="altText || undefined"
        aria-busy="true"
      >
        <span class="sa-asset__spinner" aria-hidden="true"></span>
        <span v-if="altText" class="sa-asset__placeholder-label">{{ altText }}</span>
      </div>
      <!-- Inline accessible SVG: real <title>/<text> survive sanitize; recolors via currentColor. -->
      <SafeContent
        v-else-if="isInlineSvg"
        :svg="asset.svg_inline"
        :aria-label="altText || undefined"
        :role="altText ? 'img' : undefined"
        class="sa-asset__svg"
      />
      <!-- Raster from the immutable content-addressed cache. Empty alt => decorative. -->
      <img
        v-else-if="asset.url"
        :src="asset.url"
        :alt="altText"
        :loading="eager ? 'eager' : 'lazy'"
        :decoding="eager ? 'auto' : 'async'"
        :fetchpriority="eager ? 'high' : 'auto'"
        class="sa-asset__img"
      />
    </div>
    <figcaption v-if="asset.caption" class="sa-asset__caption">
      {{ asset.caption }}
    </figcaption>
  </figure>
</template>

<style scoped>
.sa-asset {
  margin: 0;
}
.sa-asset__frame {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: var(--radius-card);
  background: var(--color-surface-2);
}
.sa-asset__img,
.sa-asset__svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.sa-asset__img {
  object-fit: contain;
}
.sa-asset__placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  padding: 0.75rem;
  text-align: center;
  background: var(--color-surface-2);
}
.sa-asset__spinner {
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 50%;
  border: 3px solid var(--color-line);
  border-top-color: var(--color-primary);
  animation: sa-asset-spin 0.9s linear infinite;
}
.sa-asset__placeholder-label {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
  max-width: 90%;
}
@keyframes sa-asset-spin {
  to {
    transform: rotate(360deg);
  }
}
/* Reduced motion: no spin — a static dot keeps the placeholder calm + accessible.
   Honor both the app toggle and the OS-level setting. */
:root[data-reduced-motion='true'] .sa-asset__spinner {
  animation: none;
  border-top-color: var(--color-line);
  background: var(--color-primary);
}
@media (prefers-reduced-motion: reduce) {
  .sa-asset__spinner {
    animation: none;
    border-top-color: var(--color-line);
    background: var(--color-primary);
  }
}
.sa-asset__svg :deep(svg) {
  width: 100%;
  height: 100%;
}
.sa-asset__caption {
  margin-top: 0.5rem;
  color: var(--color-ink-soft);
  font-size: 0.9rem;
  text-align: center;
}
/* Small thumbnails / icons shouldn't stretch full-bleed. */
.sa-asset--quiz_thumb .sa-asset__frame,
.sa-asset--icon .sa-asset__frame {
  max-width: 12rem;
  margin-inline: auto;
}
</style>

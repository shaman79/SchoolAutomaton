<script setup lang="ts">
/**
 * Renders an AssetRef (dual-coding visual). Three render paths:
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
      <!-- Inline accessible SVG: real <title>/<text> survive sanitize; recolors via currentColor. -->
      <SafeContent
        v-if="isInlineSvg"
        :svg="asset.svg_inline"
        :aria-label="altText || undefined"
        :role="altText ? 'img' : undefined"
        class="sa-asset__svg"
      />
      <!-- Raster from the immutable content-addressed cache. Empty alt => decorative. -->
      <img
        v-else
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

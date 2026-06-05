<script setup lang="ts">
/**
 * Hotspot: pick a region on an image. Regions are REAL <button> overlays (not bare SVG
 * paths) positioned by normalized 0..1 coords, so they are focusable + screen-reader
 * labelled (WCAG: keyboard operable, name from region.label). Value emitted is the region id.
 * The image is shown via /assets/{hash} (or image_url) and DOES NOT carry the answer.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeContent from '@/components/content/SafeContent.vue'
import AnswerFeedback from '@/components/questions/AnswerFeedback.vue'
import { useAnswerTiming } from '@/components/questions/useAnswerTiming'
import type {
  AnswerEvent,
  HotspotPayload,
  HotspotRegion,
  ItemPublic,
} from '@/types/question'
import type { GradeResult } from '@/types/session'

const props = withDefaults(
  defineProps<{
    item: ItemPublic
    disabled?: boolean
    feedback?: GradeResult | null
    sound?: boolean
    managed?: boolean
  }>(),
  { disabled: false, feedback: null, sound: false, managed: false },
)

const emit = defineEmits<{ (e: 'answer', payload: AnswerEvent): void }>()

const { t } = useI18n()
const payload = computed(() => props.item.payload as HotspotPayload)
const timing = useAnswerTiming(() => props.item.id)

const selected = ref<string | null>(null)
watch(
  () => props.item.id,
  () => {
    selected.value = null
    timing.reset()
  },
)

const locked = computed(() => props.disabled || !!props.feedback)

const imageSrc = computed(() => {
  if (payload.value.image_url) return payload.value.image_url
  if (payload.value.image_asset_hash) {
    const base = import.meta.env.VITE_API_BASE || '/api/v1'
    return `${base}/assets/${payload.value.image_asset_hash}`
  }
  return ''
})

/**
 * Compute a percentage bounding box from a region's normalized coords so each <button>
 * sits over its area. Shapes:
 *   rect   => [x, y, w, h]
 *   circle => [cx, cy, r]
 *   poly   => [x1,y1, x2,y2, ...] => use min/max bounds
 */
function boxStyle(region: HotspotRegion) {
  const c = region.coords
  let x = 0
  let y = 0
  let w = 0
  let h = 0
  if (region.shape === 'rect' && c.length >= 4) {
    ;[x, y, w, h] = c
  } else if (region.shape === 'circle' && c.length >= 3) {
    const [cx, cy, r] = c
    x = cx - r
    y = cy - r
    w = 2 * r
    h = 2 * r
  } else if (region.shape === 'poly' && c.length >= 4) {
    const xs: number[] = []
    const ys: number[] = []
    for (let i = 0; i + 1 < c.length; i += 2) {
      xs.push(c[i])
      ys.push(c[i + 1])
    }
    const minX = Math.min(...xs)
    const minY = Math.min(...ys)
    x = minX
    y = minY
    w = Math.max(...xs) - minX
    h = Math.max(...ys) - minY
  }
  const pct = (v: number) => `${Math.max(0, Math.min(1, v)) * 100}%`
  return {
    left: pct(x),
    top: pct(y),
    width: pct(w),
    height: pct(h),
    borderRadius: region.shape === 'circle' ? '50%' : 'var(--radius-btn)',
  }
}

function pick(region: HotspotRegion) {
  if (locked.value) return
  selected.value = region.id
}

const canSubmit = computed(() => selected.value !== null && !locked.value)
defineExpose({ submit, canSubmit })
function submit() {
  if (!canSubmit.value || selected.value === null) return
  emit('answer', timing.buildEvent(selected.value))
}

function regionLabel(region: HotspotRegion, i: number) {
  return region.label || t('q.hotspot.region_n', { n: i + 1 })
}
</script>

<template>
  <div class="sa-card sa-q">
    <SafeContent :markdown="item.stem_markdown" prose class="sa-q__stem" />
    <p class="sa-q__hint">{{ t('q.hotspot.instructions') }}</p>

    <div class="sa-hotspot" :class="{ 'sa-hotspot--noimg': !imageSrc }">
      <img v-if="imageSrc" :src="imageSrc" :alt="t('q.hotspot.image_alt')" class="sa-hotspot__img" />
      <!-- Image failed/unavailable: fall back to a legible labelled list so the learner can still
           choose (overlay pins over no image would just stack on top of each other). -->
      <p v-else class="sa-hotspot__noimg-msg" role="note">{{ t('q.hotspot.image_unavailable') }}</p>
      <button
        v-for="(region, i) in payload.regions"
        :key="region.id"
        type="button"
        class="sa-hotspot__region"
        :class="{
          'sa-hotspot__region--selected': selected === region.id,
          'sa-hotspot__region--static': !imageSrc,
        }"
        :style="imageSrc ? boxStyle(region) : undefined"
        :aria-pressed="selected === region.id"
        :aria-label="regionLabel(region, i)"
        :disabled="locked"
        @click="pick(region)"
      >
        <span class="sa-hotspot__pin" aria-hidden="true">
          {{ selected === region.id ? '✓' : i + 1 }}
        </span>
        <span v-if="!imageSrc" class="sa-hotspot__region-label">{{ regionLabel(region, i) }}</span>
      </button>
    </div>

    <button v-if="!feedback && !managed" class="sa-btn sa-btn-primary sa-q__check" :disabled="!canSubmit" @click="submit">
      {{ t('common.check') }}
    </button>

    <AnswerFeedback
      v-if="feedback"
      :correct="feedback.is_correct"
      :partial="feedback.partial_credit"
      :feedback="feedback.feedback"
      :explanation="feedback.explanation"
      :misconception="feedback.misconception"
      :sound="sound"
    />
  </div>
</template>

<style scoped>
.sa-q {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.1rem;
}
.sa-q__hint {
  color: var(--color-ink-soft);
  font-size: 0.9rem;
  margin: 0;
}
.sa-hotspot {
  position: relative;
  width: 100%;
  border-radius: var(--radius-card);
  overflow: hidden;
  background: var(--color-surface-2);
}
.sa-hotspot__img {
  display: block;
  width: 100%;
  height: auto;
}
/* No-image fallback: stack the regions as a normal labelled list. */
.sa-hotspot--noimg {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.85rem;
}
.sa-hotspot__noimg-msg {
  margin: 0;
  color: var(--color-ink-soft);
  font-size: 0.9rem;
}
.sa-hotspot__region--static {
  position: static;
  width: 100%;
  justify-content: flex-start;
  gap: 0.6rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-btn);
}
.sa-hotspot__region-label {
  font-weight: 600;
}
.sa-hotspot__region {
  position: absolute;
  /* >=44px even for tiny normalized boxes */
  min-width: var(--tap-min);
  min-height: var(--tap-min);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 3px solid color-mix(in srgb, var(--color-primary) 70%, white);
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
  cursor: pointer;
  padding: 0;
}
.sa-hotspot__region--selected {
  border-color: var(--color-mint);
  background: color-mix(in srgb, var(--color-mint) 30%, transparent);
}
.sa-hotspot__pin {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: var(--radius-pill);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-weight: 700;
  font-size: 0.9rem;
}
.sa-hotspot__region--selected .sa-hotspot__pin {
  background: var(--color-mint);
  color: var(--color-on-mint);
}
.sa-q__check {
  align-self: stretch;
  width: 100%;
}
@media (min-width: 640px) {
  .sa-q__check {
    align-self: flex-start;
    width: auto;
  }
}
</style>

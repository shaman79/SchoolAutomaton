<script setup lang="ts">
/**
 * Graceful fallback for F4's LevelBadge. Rendered when the real component is not
 * available (e.g. during concurrent development). Token-driven, accessible.
 * Accepts the same loose props so swapping in the real component is seamless.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { GamificationSnapshot } from '@/types/session'

const props = defineProps<{
  level?: number
  snapshot?: GamificationSnapshot | null
}>()

const { t } = useI18n()
const lvl = computed(() => props.level ?? props.snapshot?.level ?? 1)
</script>

<template>
  <span
    class="sa-chip sa-chip--primary shrink-0"
    :title="`${t('gamification.level')} ${lvl}`"
  >
    <span class="sr-only">{{ t('gamification.level') }}</span>
    <span aria-hidden="true" class="font-extrabold">L{{ lvl }}</span>
  </span>
</template>

<style scoped>
.sa-chip--primary {
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
}
</style>

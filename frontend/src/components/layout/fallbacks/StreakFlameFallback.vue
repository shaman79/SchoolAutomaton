<script setup lang="ts">
/**
 * Graceful fallback for F4's StreakFlame. Flame icon + day count; color is paired
 * with the icon and text so streak state is never color-only. Dims when no streak.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import SaIcon from '@/components/common/SaIcon.vue'
import type { StreakInfo } from '@/types/session'

const props = defineProps<{
  streak?: StreakInfo | null
}>()

const { t } = useI18n()
const days = computed(() => props.streak?.current ?? 0)
const active = computed(() => days.value > 0)
</script>

<template>
  <span
    class="sa-streak inline-flex shrink-0 items-center gap-1"
    :class="{ 'sa-streak--off': !active }"
    :title="`${days} ${t('gamification.streak')}`"
  >
    <SaIcon name="flame" :size="18" />
    <span class="text-sm font-bold tabular-nums" aria-hidden="true">{{ days }}</span>
    <span class="sr-only">{{ days }} {{ t('gamification.streak') }}</span>
  </span>
</template>

<style scoped>
.sa-streak {
  color: var(--color-sun);
}
.sa-streak--off {
  color: var(--color-ink-soft);
  opacity: 0.7;
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

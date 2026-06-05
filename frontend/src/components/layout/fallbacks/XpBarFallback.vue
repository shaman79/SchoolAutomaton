<script setup lang="ts">
/**
 * Graceful fallback for F4's XpBar. Compact progress toward the next level using
 * the shared accessible ProgressBar. Pulls % + value text from the snapshot.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import ProgressBar from '@/components/common/ProgressBar.vue'
import type { GamificationSnapshot } from '@/types/session'

const props = defineProps<{
  snapshot?: GamificationSnapshot | null
}>()

const { t } = useI18n()
const pct = computed(() => Math.round(props.snapshot?.level_progress_pct ?? 0))
const valueText = computed(() => {
  const s = props.snapshot
  if (!s) return ''
  return `${s.total_xp} ${t('gamification.xp')} · ${s.xp_to_next} → ${t('gamification.level')} ${s.level + 1}`
})
</script>

<template>
  <ProgressBar
    :value="pct"
    tone="primary"
    size="sm"
    :label="t('gamification.xp')"
    :value-text="valueText"
  />
</template>

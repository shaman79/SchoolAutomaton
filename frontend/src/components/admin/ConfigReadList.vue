<script setup lang="ts">
/**
 * Admin → Settings: settings that can only be changed on the server (limits, API keys, about), as a
 * definition list — label, the value in effect (with its unit), and a compact "where it comes from".
 * API keys only ever show Set / Not set (icon AND text); the key itself never reaches the browser.
 */
import SaIcon from '@/components/common/SaIcon.vue'

import type { ConfigItem } from './adminApi'
import { useConfigFormat } from './useConfigFormat'

defineProps<{ items: ConfigItem[] }>()

const { t, label, formatValue, sourceLine } = useConfigFormat()

/** The source line, plus the app default when the server's environment sets something else. */
function compactSource(item: ConfigItem): string {
  if (item.kind === 'status') {
    if (item.value) return sourceLine(item)
    return item.env_name ? t('admin.settings.status.env_hint', { env: item.env_name }) : ''
  }
  const line = sourceLine(item)
  if (item.source === 'env' && item.default_value !== null && item.default_value !== item.value) {
    return `${line} · ${t('admin.settings.app_default_is', { value: formatValue(item, item.default_value) })}`
  }
  return line
}
</script>

<template>
  <dl class="flex flex-col divide-y divide-[var(--color-line)]">
    <div
      v-for="item in items"
      :key="item.key"
      class="flex flex-col gap-0.5 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4"
      :data-key="item.key"
    >
      <dt class="font-medium [overflow-wrap:anywhere]">{{ label(item.key) }}</dt>
      <dd class="flex flex-col sm:items-end sm:text-right">
        <span v-if="item.kind === 'status'" class="inline-flex items-center gap-1.5 font-bold" data-test="value">
          <SaIcon :name="item.value ? 'check' : 'x'" :size="18" />
          {{ formatValue(item, item.value) }}
        </span>
        <span v-else class="font-bold tabular-nums [overflow-wrap:anywhere]" data-test="value">
          {{ formatValue(item, item.value) }}
        </span>
        <span
          v-if="compactSource(item)"
          class="text-xs text-[var(--color-ink-soft)] [overflow-wrap:anywhere]"
          data-test="source"
        >
          {{ compactSource(item) }}
        </span>
      </dd>
    </div>
  </dl>
</template>

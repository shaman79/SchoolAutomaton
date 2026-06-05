<script setup lang="ts">
/**
 * Admin Overview — utilitarian metric cards from GET /admin/dashboard.
 * Mobile-first: single column of cards on phones, 2-up on sm, 3-up on lg.
 * Decision breakdown + totals are rendered as labelled key/value rows (never color-only).
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { DECISION_TYPES, type DashboardOut } from './adminApi'

const props = defineProps<{ data: DashboardOut }>()
const { t, n } = useI18n()

const usd = (v: number) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(v)
const pct = (v: number) => `${(v * 100).toFixed(1)}%`

interface Metric {
  key: string
  label: string
  value: string
  /** When set, marks a metric that warrants attention (shown with an icon, not color alone). */
  alert?: boolean
}

const metrics = computed<Metric[]>(() => {
  const d = props.data
  return [
    { key: 'requests_24h', label: t('admin.overview.requests_24h'), value: n(d.requests_24h) },
    { key: 'cache_hit_rate', label: t('admin.overview.cache_hit_rate'), value: pct(d.cache_hit_rate) },
    { key: 'anthropic_cost', label: t('admin.overview.anthropic_cost'), value: usd(d.anthropic_cost_usd) },
    { key: 'replicate_cost', label: t('admin.overview.replicate_cost'), value: usd(d.replicate_cost_usd) },
    { key: 'crisis_events', label: t('admin.overview.crisis_events'), value: n(d.crisis_events), alert: d.crisis_events > 0 },
    { key: 'refusals', label: t('admin.overview.refusals'), value: n(d.refusals) },
    {
      key: 'injection_attempts',
      label: t('admin.overview.injection_attempts'),
      value: n(d.injection_attempts),
      alert: d.injection_attempts > 0,
    },
  ]
})

// Decision breakdown: ensure all known decision types appear (0-fill), keep deterministic order.
const decisions = computed(() => {
  const b = props.data.decisions_breakdown ?? {}
  const known = DECISION_TYPES.map((dt) => ({ key: dt, label: t(`admin.overview.decision.${dt}`), count: b[dt] ?? 0 }))
  const extras = Object.keys(b)
    .filter((k) => !DECISION_TYPES.includes(k as (typeof DECISION_TYPES)[number]))
    .map((k) => ({ key: k, label: k, count: b[k] }))
  return [...known, ...extras]
})
const decisionsTotal = computed(() => decisions.value.reduce((s, d) => s + d.count, 0))

const totals = computed(() => [
  { key: 'profiles', label: t('admin.overview.profiles_total'), value: props.data.profiles_total },
  { key: 'lessons', label: t('admin.overview.lessons_total'), value: props.data.lessons_total },
  { key: 'quizzes', label: t('admin.overview.quizzes_total'), value: props.data.quizzes_total },
])
</script>

<template>
  <div class="flex flex-col gap-4">
    <h2 class="text-lg font-bold">{{ t('admin.overview.title') }}</h2>

    <!-- Metric tiles -->
    <ul class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <li v-for="m in metrics" :key="m.key" class="sa-card p-4">
        <p class="flex items-center gap-1.5 text-sm font-medium text-[var(--color-ink-soft)]">
          <span
            v-if="m.alert"
            aria-hidden="true"
            class="inline-grid h-4 w-4 place-items-center rounded-full text-[0.7rem] font-bold text-[var(--color-on-coral)]"
            style="background: var(--color-coral)"
          >!</span>
          {{ m.label }}
        </p>
        <p class="mt-1 text-2xl font-bold tabular-nums">{{ m.value }}</p>
      </li>
    </ul>

    <!-- Decision breakdown -->
    <div class="sa-card p-4">
      <h3 class="text-base font-bold">{{ t('admin.overview.decisions') }}</h3>
      <p v-if="decisionsTotal === 0" class="mt-2 text-sm text-[var(--color-ink-soft)]">
        {{ t('admin.overview.no_decisions') }}
      </p>
      <dl v-else class="mt-3 flex flex-col gap-3">
        <div v-for="d in decisions" :key="d.key">
          <div class="flex items-baseline justify-between gap-2">
            <dt class="text-sm font-medium">{{ d.label }}</dt>
            <dd class="text-sm font-bold tabular-nums">
              {{ n(d.count) }}
              <span class="text-[var(--color-ink-soft)]">
                ({{ decisionsTotal ? Math.round((d.count / decisionsTotal) * 100) : 0 }}%)
              </span>
            </dd>
          </div>
          <!-- proportion bar (decorative; the numeric value above carries the meaning) -->
          <div class="mt-1 h-1.5 overflow-hidden rounded-full" style="background: var(--color-surface-2)" aria-hidden="true">
            <div
              class="h-full rounded-full"
              style="background: var(--color-primary)"
              :style="{ width: `${decisionsTotal ? (d.count / decisionsTotal) * 100 : 0}%` }"
            />
          </div>
        </div>
      </dl>
    </div>

    <!-- Totals -->
    <div class="sa-card p-4">
      <h3 class="text-base font-bold">{{ t('admin.overview.totals') }}</h3>
      <dl class="mt-3 grid grid-cols-3 gap-2 text-center">
        <div v-for="tot in totals" :key="tot.key" class="rounded-[var(--radius-btn)] p-2" style="background: var(--color-surface-2)">
          <dd class="text-xl font-bold tabular-nums">{{ n(tot.value) }}</dd>
          <dt class="text-xs text-[var(--color-ink-soft)]">{{ tot.label }}</dt>
        </div>
      </dl>
    </div>
  </div>
</template>

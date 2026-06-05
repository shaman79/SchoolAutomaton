<script setup lang="ts">
/**
 * Admin Audit — paginated SanitizationAudit browser (GET /admin/audit).
 * Filters: decision_type + injection_only. Topic is HASHED in storage — the UI states this
 * explicitly and shows only the one-way hash, never the student's words.
 *
 * Mobile-first: rows render as stacked cards on phones; a real table appears at lg.
 * Emits `unauthorized` so the parent view can redirect to /admin/login on a 401/403.
 */
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { api } from '@/lib/api'

import { DECISION_TYPES, isUnauthorized, type AuditPage, type AuditRecord } from './adminApi'

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ unauthorized: [] }>()
const { t, n, d } = useI18n()

const decisionType = ref<string>('')
const injectionOnly = ref(false)
const page = ref(1)
const pageSize = 50

const loading = ref(true)
const error = ref<string | null>(null)
const data = ref<AuditPage | null>(null)

function pages(): number {
  if (!data.value) return 1
  return Math.max(1, Math.ceil(data.value.total / data.value.page_size))
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const params: Record<string, string> = { page: String(page.value), page_size: String(pageSize) }
    if (decisionType.value) params.decision_type = decisionType.value
    if (injectionOnly.value) params.injection_only = 'true'
    data.value = (await api.adminAudit(props.token, params)) as AuditPage
  } catch (e) {
    if (isUnauthorized(e)) {
      emit('unauthorized')
      return
    }
    error.value = t('admin.load_error')
  } finally {
    loading.value = false
  }
}

// Filter changes reset to page 1.
watch([decisionType, injectionOnly], () => {
  page.value = 1
  load()
})
watch(page, load)
onMounted(load)

function fmtTs(ts: string): string {
  try {
    return d(new Date(ts), 'long')
  } catch {
    return ts
  }
}
function decisionLabel(dt: string): string {
  return DECISION_TYPES.includes(dt as (typeof DECISION_TYPES)[number])
    ? t(`admin.overview.decision.${dt}`)
    : dt
}
function shortHash(h: string | null): string {
  if (!h) return t('admin.audit.no_flags')
  return h.length > 16 ? `${h.slice(0, 16)}…` : h
}
function reasonText(r: AuditRecord): string {
  return r.reason && r.reason.trim() ? r.reason : t('admin.audit.no_flags')
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <h2 class="text-lg font-bold">{{ t('admin.audit.title') }}</h2>

    <!-- Filters -->
    <div class="sa-card flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
      <label class="flex flex-1 flex-col gap-1 text-sm font-medium">
        {{ t('admin.audit.filter_decision') }}
        <select
          v-model="decisionType"
          class="min-h-[var(--tap-min)] rounded-[var(--radius-btn)] border border-[var(--color-line)] bg-[var(--color-surface-2)] px-3"
        >
          <option value="">{{ t('admin.audit.filter_all') }}</option>
          <option v-for="dt in DECISION_TYPES" :key="dt" :value="dt">{{ decisionLabel(dt) }}</option>
        </select>
      </label>
      <label class="flex min-h-[var(--tap-min)] items-center gap-2 text-sm font-medium">
        <input v-model="injectionOnly" type="checkbox" class="h-5 w-5" />
        {{ t('admin.audit.injection_only') }}
      </label>
    </div>

    <!-- Privacy note: topic is hashed -->
    <p class="flex items-start gap-2 rounded-[var(--radius-btn)] p-3 text-sm" style="background: var(--color-bg-tint)">
      <span aria-hidden="true" class="font-bold text-[var(--color-primary)]">i</span>
      <span>{{ t('admin.audit.topic_hashed_note') }}</span>
    </p>

    <div v-if="loading" class="flex justify-center py-10">
      <LoadingSpinner :size="32" :label="t('common.loading')" />
    </div>

    <p v-else-if="error" class="text-[var(--color-coral)]" role="alert">
      {{ error }}
      <button class="sa-btn sa-btn-ghost ml-2" @click="load">{{ t('admin.retry') }}</button>
    </p>

    <EmptyState
      v-else-if="data && data.items.length === 0"
      icon="check"
      :title="t('admin.audit.empty_title')"
      :description="t('admin.audit.empty_desc')"
      announce
    />

    <template v-else-if="data">
      <!-- Mobile: stacked cards -->
      <ul class="flex flex-col gap-3 lg:hidden">
        <li v-for="r in data.items" :key="r.id" class="sa-card p-4">
          <div class="flex items-center justify-between gap-2">
            <span class="sa-chip">{{ decisionLabel(r.decision_type) }}</span>
            <time class="text-xs text-[var(--color-ink-soft)]">{{ fmtTs(r.ts) }}</time>
          </div>
          <dl class="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
            <dt class="text-[var(--color-ink-soft)]">{{ t('admin.audit.col_request') }}</dt>
            <dd class="truncate font-mono text-xs" :title="r.request_id">{{ r.request_id }}</dd>
            <dt class="text-[var(--color-ink-soft)]">{{ t('admin.audit.col_lang') }}</dt>
            <dd>{{ r.language || t('admin.audit.no_flags') }}</dd>
            <dt class="text-[var(--color-ink-soft)]">{{ t('admin.audit.col_suspicion') }}</dt>
            <dd class="tabular-nums">{{ r.suspicion_score.toFixed(2) }}</dd>
            <dt class="text-[var(--color-ink-soft)]">{{ t('admin.audit.col_injection') }}</dt>
            <dd>
              <span class="inline-flex items-center gap-1 font-semibold" :class="r.injection_detected ? 'text-[var(--color-coral)]' : ''">
                <span aria-hidden="true">{{ r.injection_detected ? '⚠' : '✓' }}</span>
                {{ r.injection_detected ? t('admin.audit.injection_yes') : t('admin.audit.injection_no') }}
              </span>
            </dd>
            <dt class="text-[var(--color-ink-soft)]">{{ t('admin.audit.col_length') }}</dt>
            <dd class="tabular-nums">{{ n(r.raw_length) }}</dd>
            <dt class="text-[var(--color-ink-soft)]">{{ t('admin.audit.col_topic_hash') }}</dt>
            <dd class="truncate font-mono text-xs" :title="r.topic_hash || ''">{{ shortHash(r.topic_hash) }}</dd>
          </dl>
          <p v-if="r.safety_flags && r.safety_flags.length" class="mt-2 flex flex-wrap gap-1">
            <span v-for="f in r.safety_flags" :key="f" class="sa-chip text-xs">{{ f }}</span>
          </p>
          <p class="mt-2 text-sm text-[var(--color-ink-soft)]">{{ reasonText(r) }}</p>
        </li>
      </ul>

      <!-- Desktop: table -->
      <div class="hidden overflow-x-auto lg:block">
        <table class="w-full border-collapse text-sm">
          <thead>
            <tr class="border-b border-[var(--color-line)] text-left text-[var(--color-ink-soft)]">
              <th scope="col" class="py-2 pr-3 font-semibold">{{ t('admin.audit.col_time') }}</th>
              <th scope="col" class="py-2 pr-3 font-semibold">{{ t('admin.audit.col_decision') }}</th>
              <th scope="col" class="py-2 pr-3 font-semibold">{{ t('admin.audit.col_lang') }}</th>
              <th scope="col" class="py-2 pr-3 font-semibold">{{ t('admin.audit.col_suspicion') }}</th>
              <th scope="col" class="py-2 pr-3 font-semibold">{{ t('admin.audit.col_injection') }}</th>
              <th scope="col" class="py-2 pr-3 font-semibold">{{ t('admin.audit.col_flags') }}</th>
              <th scope="col" class="py-2 pr-3 font-semibold">{{ t('admin.audit.col_topic_hash') }}</th>
              <th scope="col" class="py-2 font-semibold">{{ t('admin.audit.col_reason') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in data.items" :key="r.id" class="border-b border-[var(--color-line)] align-top">
              <td class="py-2 pr-3 whitespace-nowrap text-xs text-[var(--color-ink-soft)]">{{ fmtTs(r.ts) }}</td>
              <td class="py-2 pr-3"><span class="sa-chip">{{ decisionLabel(r.decision_type) }}</span></td>
              <td class="py-2 pr-3">{{ r.language || t('admin.audit.no_flags') }}</td>
              <td class="py-2 pr-3 tabular-nums">{{ r.suspicion_score.toFixed(2) }}</td>
              <td class="py-2 pr-3">
                <span class="inline-flex items-center gap-1 font-semibold" :class="r.injection_detected ? 'text-[var(--color-coral)]' : ''">
                  <span aria-hidden="true">{{ r.injection_detected ? '⚠' : '✓' }}</span>
                  {{ r.injection_detected ? t('admin.audit.injection_yes') : t('admin.audit.injection_no') }}
                </span>
              </td>
              <td class="py-2 pr-3">
                <span v-if="r.safety_flags && r.safety_flags.length" class="flex flex-wrap gap-1">
                  <span v-for="f in r.safety_flags" :key="f" class="sa-chip text-xs">{{ f }}</span>
                </span>
                <span v-else>{{ t('admin.audit.no_flags') }}</span>
              </td>
              <td class="py-2 pr-3 font-mono text-xs" :title="r.topic_hash || ''">{{ shortHash(r.topic_hash) }}</td>
              <td class="py-2 max-w-xs text-[var(--color-ink-soft)]">{{ reasonText(r) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-[var(--color-ink-soft)]" aria-live="polite">
          {{ t('admin.audit.showing', { count: data.items.length, total: data.total }) }}
        </p>
        <div class="flex items-center gap-2">
          <button class="sa-btn sa-btn-ghost" :disabled="page <= 1" @click="page = Math.max(1, page - 1)">
            {{ t('admin.audit.prev') }}
          </button>
          <span class="text-sm tabular-nums">{{ t('admin.audit.page_of', { page, pages: pages() }) }}</span>
          <button class="sa-btn sa-btn-ghost" :disabled="page >= pages()" @click="page = Math.min(pages(), page + 1)">
            {{ t('admin.audit.next') }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

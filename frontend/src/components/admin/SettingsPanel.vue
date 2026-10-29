<script setup lang="ts">
/**
 * Admin → Settings (GET /admin/config): what the backend runs with right now and where each value
 * comes from, today's AI spending against the daily budget, and which models really answered today.
 * An admin who may edit can switch the AI models and change the daily budget (PUT /admin/config/{key})
 * or undo such a change (DELETE); everything else is changed on the server and only shown here.
 *
 * Mobile-first: stacked rows and full-width controls on phones. Emits `unauthorized` on a 401/403
 * so the parent view can send the admin back to the login.
 */
import { computed, onMounted, ref } from 'vue'

import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { toast } from '@/components/common/useToasts'
import { api } from '@/lib/api'

import ConfigItemRow from './ConfigItemRow.vue'
import ConfigReadList from './ConfigReadList.vue'
import { isUnauthorized, type AdminConfigOut, type ConfigItem, type ModelUsageToday } from './adminApi'
import { useConfigFormat } from './useConfigFormat'

const props = defineProps<{ token: string }>()
const emit = defineEmits<{ unauthorized: [] }>()

const { t, label, usd, num, percent, dateTime } = useConfigFormat()

const loading = ref(true)
const refreshing = ref(false)
const error = ref<string | null>(null)
const data = ref<AdminConfigOut | null>(null)
let loadSeq = 0

/** `quiet`: keep showing the current values while reloading (after a save, or Refresh). */
async function load(quiet = false) {
  const seq = ++loadSeq
  if (quiet && data.value) refreshing.value = true
  else {
    loading.value = true
    error.value = null
  }
  try {
    const cfg = (await api.adminConfig(props.token)) as AdminConfigOut
    if (seq !== loadSeq) return // a newer load is on its way
    data.value = cfg
    error.value = null
  } catch (e) {
    if (isUnauthorized(e)) {
      emit('unauthorized')
      return
    }
    if (seq !== loadSeq) return
    if (data.value) toast.error(t('admin.load_error'))
    else error.value = t('admin.load_error')
  } finally {
    if (seq === loadSeq) {
      loading.value = false
      refreshing.value = false
    }
  }
}
onMounted(() => load())

/** A row saved / undone: show its new value at once, then reload so the budget summary follows. */
function onUpdated(updated: ConfigItem) {
  if (data.value) {
    const idx = data.value.items.findIndex((i) => i.key === updated.key)
    if (idx !== -1) data.value.items[idx] = updated
  }
  void load(true)
}

const items = computed(() => data.value?.items ?? [])
const canEdit = computed(() => data.value?.can_edit === true)
const inGroup = (group: string) => items.value.filter((i) => i.group === group)

const KNOWN_GROUPS = ['models', 'spending', 'limits', 'keys', 'about']
const modelItems = computed(() => inGroup('models'))
const spendingItems = computed(() => inGroup('spending'))
/** Read-only sections in display order; settings of a group this build doesn't know go to "Other". */
const otherSections = computed(() =>
  [
    { id: 'limits', items: inGroup('limits') },
    { id: 'keys', items: inGroup('keys') },
    { id: 'about', items: inGroup('about') },
    { id: 'other', items: items.value.filter((i) => !KNOWN_GROUPS.includes(i.group)) },
  ].filter((s) => s.items.length > 0),
)
const editableOf = (list: ConfigItem[]) => list.filter((i) => i.editable)
const readOnlyOf = (list: ConfigItem[]) => list.filter((i) => !i.editable)

// --------------------------------------------------------------------------- spending today
const budget = computed(() => data.value?.budget_usd ?? 0)
const spent = computed(() => data.value?.spent_today_usd ?? 0)
const hasCap = computed(() => budget.value > 0)
const ratio = computed(() => (hasCap.value ? spent.value / budget.value : 0))
const reached = computed(() => hasCap.value && spent.value >= budget.value)
const spentText = computed(() =>
  hasCap.value
    ? t('admin.settings.spending.spent_of', { spent: usd(spent.value), budget: usd(budget.value) })
    : t('admin.settings.spending.spent_no_cap', { spent: usd(spent.value) }),
)
const usedText = computed(() => t('admin.settings.spending.used', { pct: percent(ratio.value) }))
const dayStartText = computed(() =>
  t('admin.settings.spending.day_start', { local: dateTime(data.value?.day_started_at ?? null, 'time') }),
)
const usage = computed(() => data.value?.usage_today ?? [])

function callsText(u: ModelUsageToday): string {
  return t('admin.settings.spending.calls', { n: num(u.calls) }, u.calls)
}
function costText(u: ModelUsageToday): string {
  return u.cost_usd === null ? t('admin.settings.spending.price_unknown') : usd(u.cost_usd)
}
/** Which model settings name this model now ("In use: Main AI model") — to verify a switch. */
function inUseAs(u: ModelUsageToday): string[] {
  return modelItems.value.filter((i) => i.value === u.model).map((i) => label(i.key))
}

const noteClass = 'flex items-start gap-2 rounded-[var(--radius-btn)] p-3 text-sm'
</script>

<template>
  <div class="flex flex-col gap-5">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p class="text-sm text-[var(--color-ink-soft)]">{{ t('admin.settings.intro') }}</p>
      <button
        v-if="data"
        type="button"
        class="sa-btn sa-btn-ghost w-full shrink-0 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
        :disabled="refreshing || loading"
        :aria-busy="refreshing ? 'true' : undefined"
        data-test="refresh"
        @click="load(true)"
      >
        {{ t('admin.refresh') }}
      </button>
    </div>

    <div v-if="loading" class="flex justify-center py-10">
      <LoadingSpinner :size="32" :label="t('common.loading')" />
    </div>

    <p v-else-if="error" class="flex flex-wrap items-center gap-2" role="alert">
      <span>{{ error }}</span>
      <button type="button" class="sa-btn sa-btn-ghost" @click="load()">{{ t('admin.retry') }}</button>
    </p>

    <template v-else-if="data">
      <p v-if="!canEdit" :class="noteClass" style="background: var(--color-bg-tint)" data-test="read-only-note">
        <span aria-hidden="true" class="font-bold text-[var(--color-primary)]">i</span>
        <span>{{ t('admin.settings.read_only_note') }}</span>
      </p>

      <!-- AI models -->
      <section v-if="modelItems.length" class="sa-card flex flex-col gap-4 p-4" aria-labelledby="cfg-sec-models">
        <h2 id="cfg-sec-models" class="text-lg font-bold">{{ t('admin.settings.sections.models') }}</h2>
        <ul v-if="editableOf(modelItems).length" class="flex flex-col divide-y divide-[var(--color-line)]">
          <li v-for="item in editableOf(modelItems)" :key="item.key" class="py-4 first:pt-0 last:pb-0">
            <ConfigItemRow
              :item="item"
              :token="token"
              :can-edit="canEdit"
              @updated="onUpdated"
              @unauthorized="emit('unauthorized')"
            />
          </li>
        </ul>
        <ConfigReadList v-if="readOnlyOf(modelItems).length" :items="readOnlyOf(modelItems)" />
      </section>

      <!-- AI spending today -->
      <section class="sa-card flex flex-col gap-4 p-4" aria-labelledby="cfg-sec-spending" data-test="spending">
        <h2 id="cfg-sec-spending" class="text-lg font-bold">{{ t('admin.settings.sections.spending') }}</h2>

        <div class="flex flex-col gap-1.5">
          <p class="text-lg font-bold tabular-nums" data-test="spent">{{ spentText }}</p>
          <template v-if="hasCap">
            <!-- decorative: the text around it carries the meaning -->
            <div class="h-2.5 overflow-hidden rounded-full" style="background: var(--color-surface-2)" aria-hidden="true">
              <div
                class="h-full rounded-full"
                :style="{
                  width: `${Math.min(100, ratio * 100)}%`,
                  background: reached ? 'var(--color-coral)' : 'var(--color-primary)',
                }"
              />
            </div>
            <p class="text-sm tabular-nums" data-test="used">{{ usedText }}</p>
          </template>
          <p
            v-if="reached"
            :class="noteClass"
            class="border-l-4 border-[var(--color-coral)]"
            style="background: var(--color-surface-2)"
            data-test="reached"
          >
            <span
              aria-hidden="true"
              class="inline-grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs font-bold text-[var(--color-on-coral)]"
              style="background: var(--color-coral)"
            >!</span>
            <span>{{ t('admin.settings.spending.reached') }}</span>
          </p>
          <p class="text-xs text-[var(--color-ink-soft)]">{{ dayStartText }}</p>
        </div>

        <ul v-if="editableOf(spendingItems).length" class="flex flex-col divide-y divide-[var(--color-line)] border-t border-[var(--color-line)] pt-4">
          <li v-for="item in editableOf(spendingItems)" :key="item.key" class="py-4 first:pt-0 last:pb-0">
            <ConfigItemRow
              :item="item"
              :token="token"
              :can-edit="canEdit"
              @updated="onUpdated"
              @unauthorized="emit('unauthorized')"
            />
          </li>
        </ul>
        <ConfigReadList v-if="readOnlyOf(spendingItems).length" :items="readOnlyOf(spendingItems)" />

        <!-- Which models really answered today -->
        <div class="flex flex-col gap-2 border-t border-[var(--color-line)] pt-4" data-test="usage">
          <h3 class="text-base font-bold">{{ t('admin.settings.spending.usage_title') }}</h3>
          <p class="text-sm text-[var(--color-ink-soft)]">{{ t('admin.settings.spending.usage_help') }}</p>
          <p v-if="usage.length === 0" :class="noteClass" style="background: var(--color-surface-2)" data-test="usage-empty">
            {{ t('admin.settings.spending.usage_empty') }}
          </p>
          <ul v-else class="flex flex-col divide-y divide-[var(--color-line)]">
            <li
              v-for="u in usage"
              :key="`${u.provider}/${u.model}`"
              class="flex flex-col gap-1 py-3"
              data-test="usage-row"
            >
              <div class="flex items-baseline justify-between gap-3">
                <span class="min-w-0 font-bold [overflow-wrap:anywhere]">{{ u.model }}</span>
                <span
                  class="shrink-0 tabular-nums"
                  :class="u.cost_usd === null ? 'text-sm text-[var(--color-ink-soft)]' : 'font-bold'"
                >{{ costText(u) }}</span>
              </div>
              <p class="text-sm text-[var(--color-ink-soft)]">
                {{ u.provider }} · {{ callsText(u) }}<template v-if="u.last_call_at">
                  · {{ t('admin.settings.spending.last_call', { time: dateTime(u.last_call_at) }) }}</template>
              </p>
              <p v-if="inUseAs(u).length" class="flex flex-wrap gap-1">
                <span v-for="l in inUseAs(u)" :key="l" class="sa-chip text-xs">
                  <span aria-hidden="true">✓</span>
                  {{ t('admin.settings.spending.in_use_as', { label: l }) }}
                </span>
              </p>
            </li>
          </ul>
        </div>
      </section>

      <!-- Limits, API keys, About (+ anything newer this build doesn't know) -->
      <section
        v-for="sec in otherSections"
        :key="sec.id"
        class="sa-card flex flex-col gap-4 p-4"
        :aria-labelledby="`cfg-sec-${sec.id}`"
        :data-test="`section-${sec.id}`"
      >
        <h2 :id="`cfg-sec-${sec.id}`" class="text-lg font-bold">{{ t(`admin.settings.sections.${sec.id}`) }}</h2>
        <ul v-if="editableOf(sec.items).length" class="flex flex-col divide-y divide-[var(--color-line)]">
          <li v-for="item in editableOf(sec.items)" :key="item.key" class="py-4 first:pt-0 last:pb-0">
            <ConfigItemRow
              :item="item"
              :token="token"
              :can-edit="canEdit"
              @updated="onUpdated"
              @unauthorized="emit('unauthorized')"
            />
          </li>
        </ul>
        <ConfigReadList v-if="readOnlyOf(sec.items).length" :items="readOnlyOf(sec.items)" />
      </section>
    </template>
  </div>
</template>

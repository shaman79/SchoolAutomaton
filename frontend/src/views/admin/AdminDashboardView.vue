<script setup lang="ts">
/**
 * Admin console: Overview (GET /admin/dashboard), Settings (what the backend runs with; switch the
 * AI models / daily budget) and Audit (sanitization log). The open tab lives in the URL (`?tab=`), so
 * a reload or a shared link opens the same tab. An expired session (401/403 from any tab) clears the
 * token and returns to the login, which brings the admin back here afterwards.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AuditTable from '@/components/admin/AuditTable.vue'
import DashboardCards from '@/components/admin/DashboardCards.vue'
import SettingsPanel from '@/components/admin/SettingsPanel.vue'
import { isUnauthorized, type DashboardOut } from '@/components/admin/adminApi'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { toast } from '@/components/common/useToasts'
import { api } from '@/lib/api'
import { ADMIN_TOKEN_KEY } from '@/router'

const TABS = ['overview', 'settings', 'audit'] as const
type Tab = (typeof TABS)[number]

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const token = localStorage.getItem(ADMIN_TOKEN_KEY) || ''

const tab = computed<Tab>(() => {
  const q = route.query.tab
  return typeof q === 'string' && (TABS as readonly string[]).includes(q) ? (q as Tab) : 'overview'
})

function selectTab(next: Tab) {
  if (next === tab.value) return
  const query = { ...route.query }
  if (next === 'overview') delete query.tab
  else query.tab = next
  void router.replace({ query })
}

// Arrow keys / Home / End move between tabs (WAI-ARIA tabs pattern, automatic activation).
const tablist = ref<HTMLElement | null>(null)
function onTabKey(e: KeyboardEvent, index: number) {
  let next: number | null = null
  if (e.key === 'ArrowRight') next = (index + 1) % TABS.length
  else if (e.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = TABS.length - 1
  if (next === null) return
  e.preventDefault()
  const name = TABS[next]
  selectTab(name)
  void nextTick(() => tablist.value?.querySelector<HTMLButtonElement>(`#admin-tab-${name}`)?.focus())
}

// --------------------------------------------------------------------------- session
let leaving = false
function onUnauthorized() {
  if (leaving) return // several panels may report the same expired session
  leaving = true
  localStorage.removeItem(ADMIN_TOKEN_KEY)
  toast.warning(t('admin.session_expired'))
  void router.replace({ name: 'admin-login', query: { redirect: route.fullPath } })
}
function logout() {
  localStorage.removeItem(ADMIN_TOKEN_KEY)
  void router.push({ name: 'admin-login' })
}

// --------------------------------------------------------------------------- overview
const dashboard = ref<DashboardOut | null>(null)
const dashLoading = ref(false)
const dashError = ref<string | null>(null)

async function loadDashboard() {
  dashLoading.value = true
  dashError.value = null
  try {
    dashboard.value = (await api.adminDashboard(token)) as DashboardOut
  } catch (e) {
    if (isUnauthorized(e)) {
      onUnauthorized()
      return
    }
    dashError.value = t('admin.load_error')
  } finally {
    dashLoading.value = false
  }
}
// Loaded the first time the Overview is opened (not when the admin lands straight on another tab).
watch(
  tab,
  (current) => {
    if (current === 'overview' && !dashboard.value && !dashLoading.value) void loadDashboard()
  },
  { immediate: true },
)
</script>

<template>
  <section class="flex flex-col gap-4 py-6">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-2xl font-bold">{{ t('admin.title') }}</h1>
      <button type="button" class="sa-btn sa-btn-ghost" @click="logout">{{ t('admin.sign_out') }}</button>
    </header>

    <div
      ref="tablist"
      role="tablist"
      :aria-label="t('admin.tabs.label')"
      class="grid grid-cols-3 gap-1 rounded-[var(--radius-btn)] p-1"
      style="background: var(--color-surface-2)"
    >
      <button
        v-for="(name, i) in TABS"
        :id="`admin-tab-${name}`"
        :key="name"
        type="button"
        role="tab"
        :aria-selected="tab === name ? 'true' : 'false'"
        :aria-controls="`admin-panel-${name}`"
        :tabindex="tab === name ? 0 : -1"
        class="min-h-[var(--tap-min)] min-w-0 rounded-[calc(var(--radius-btn)-0.25rem)] px-2 text-sm font-semibold [overflow-wrap:anywhere] sm:text-base"
        :class="
          tab === name
            ? 'bg-[var(--color-surface)] text-[var(--color-ink)] underline decoration-[var(--color-primary)] decoration-2 underline-offset-4 shadow-sm'
            : 'text-[var(--color-ink-soft)]'
        "
        :data-test="`tab-${name}`"
        @click="selectTab(name)"
        @keydown="onTabKey($event, i)"
      >
        {{ t(`admin.tabs.${name}`) }}
      </button>
    </div>

    <div
      :id="`admin-panel-${tab}`"
      role="tabpanel"
      :aria-labelledby="`admin-tab-${tab}`"
      tabindex="0"
      class="rounded-[var(--radius-btn)]"
    >
      <template v-if="tab === 'overview'">
        <div v-if="dashLoading" class="flex justify-center py-10">
          <LoadingSpinner :size="32" :label="t('common.loading')" />
        </div>
        <p v-else-if="dashError" class="flex flex-wrap items-center gap-2" role="alert">
          <span>{{ dashError }}</span>
          <button type="button" class="sa-btn sa-btn-ghost" @click="loadDashboard">{{ t('admin.retry') }}</button>
        </p>
        <DashboardCards v-else-if="dashboard" :data="dashboard" />
      </template>
      <SettingsPanel v-else-if="tab === 'settings'" :token="token" @unauthorized="onUnauthorized" />
      <AuditTable v-else :token="token" @unauthorized="onUnauthorized" />
    </div>
  </section>
</template>

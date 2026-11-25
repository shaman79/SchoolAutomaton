<script setup lang="ts">
/**
 * ParentsView — "Overview for parents" on the LEARNER's own device (GET /profiles/me/summary): the
 * calm overview of the last 7 or 30 days (ParentSummaryPanel), and the parent code that lets a parent
 * follow it — and give tasks — from their own phone (ParentCodeCard, /parent). A device without a
 * learner points a parent to the parent view instead. Mobile-first.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import ParentCodeCard from '@/components/parents/ParentCodeCard.vue'
import ParentSummaryPanel from '@/components/parents/ParentSummaryPanel.vue'
import PeriodSwitch from '@/components/parents/PeriodSwitch.vue'
import { api } from '@/lib/api'
import { useParentStore, type SummaryDays } from '@/stores/parent'
import { useSessionStore } from '@/stores/session'
import type { ParentSummary } from '@/types/session'

const { t } = useI18n()
const session = useSessionStore()
const parent = useParentStore()

const hasProfile = computed(() => !!session.resumeCode)
const summary = ref<ParentSummary | null>(null)
const loading = ref(false)
const failed = ref(false)
const days = computed<SummaryDays>({
  get: () => parent.period,
  set: (d) => parent.setPeriod(d),
})

// Only the latest load may land (switching 7 ↔ 30 quickly must not show the older answer).
let seq = 0
async function load() {
  const mine = ++seq
  loading.value = true
  failed.value = false
  try {
    const s = await api.getSummary(days.value)
    if (mine === seq) summary.value = s
  } catch {
    if (mine === seq) failed.value = true
  } finally {
    if (mine === seq) loading.value = false
  }
}

onMounted(() => {
  if (hasProfile.value) void load()
})
watch(days, () => {
  if (hasProfile.value) void load()
})
</script>

<template>
  <section class="sa-parents">
    <header class="sa-parents__head">
      <h1 class="sa-parents__title">{{ t('parents.title') }}</h1>
    </header>

    <div v-if="!hasProfile" class="sa-card sa-parents__note">
      <p>{{ t('stats.no_profile') }}</p>
      <p>{{ t('parents.no_profile_parent') }}</p>
      <SaButton variant="primary" icon="users" :to="{ name: 'parent' }">{{ t('parents.open_parent') }}</SaButton>
    </div>

    <template v-else>
      <ParentCodeCard />

      <!-- The overview, for the period chosen right here -->
      <div class="sa-parents__bar">
        <h2 class="sa-parents__h2">{{ t('parents.subtitle', { n: days }) }}</h2>
        <PeriodSwitch v-model="days" />
      </div>

      <p v-if="loading && !summary" class="sa-parents__note" role="status">{{ t('common.loading') }}</p>

      <div v-else-if="failed" class="sa-card sa-parents__note" role="alert">
        <p>{{ t('parents.load_error') }}</p>
        <SaButton variant="ghost" @click="load">{{ t('common.retry') }}</SaButton>
      </div>

      <ParentSummaryPanel
        v-else-if="summary"
        :summary="summary"
        :class="{ 'sa-parents__stale': loading }"
        :aria-busy="loading"
      />
    </template>
  </section>
</template>

<style scoped>
.sa-parents {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.5rem 0 2rem;
}
.sa-parents__head {
  text-align: center;
}
.sa-parents__title {
  font-size: 1.5rem;
  font-weight: 800;
}
/* Heading + period switch on one line when they fit; the switch drops below on a narrow phone. */
.sa-parents__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem 1rem;
  margin-top: 0.4rem;
}
.sa-parents__h2 {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 800;
}
.sa-parents__note {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 1.5rem 1.1rem;
  text-align: center;
  color: var(--color-ink-soft);
}
.sa-parents__note p {
  margin: 0;
}
/* While the other period loads, the current one stays (dimmed) instead of flashing away. */
.sa-parents__stale {
  opacity: 0.6;
  transition: opacity 0.15s;
}
</style>

<script setup lang="ts">
/**
 * HistoryView — "My lessons": the learner's past (and in-progress) lessons & quizzes, tied to their
 * resume code. Lets them re-open a session after a refresh / back / new visit. Mobile-first.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import SaIcon from '@/components/common/SaIcon.vue'
import { api } from '@/lib/api'
import { humanizeSubject } from '@/lib/format'
import { useSessionStore } from '@/stores/session'
import type { LearningSessionSummary } from '@/types/session'

const { t, locale } = useI18n()
const router = useRouter()
const session = useSessionStore()

const items = ref<LearningSessionSummary[]>([])
const loading = ref(false)
const error = ref(false)

const hasProfile = computed(() => !!session.resumeCode)

onMounted(async () => {
  if (!hasProfile.value) return
  loading.value = true
  error.value = false
  try {
    items.value = await api.getMyRequests()
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
})

function dateFmt(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(d)
}

/** Where a card leads: ready→lesson/test, generating→loading. Errored cards are not navigable. */
function targetOf(it: LearningSessionSummary) {
  if (it.status === 'generating' || it.status === 'queued') {
    return { name: 'loading', params: { sessionId: it.request_id } }
  }
  if (it.status === 'ready') {
    const name = it.mode === 'test' ? 'test' : 'lesson'
    return { name, params: { sessionId: it.request_id } }
  }
  return null
}

function open(it: LearningSessionSummary) {
  const to = targetOf(it)
  if (to) router.push(to)
}
</script>

<template>
  <section class="sa-hist">
    <h1 class="sa-hist__title">{{ t('history.title') }}</h1>

    <!-- No profile yet -->
    <div v-if="!hasProfile" class="sa-card sa-hist__empty">
      <SaIcon name="books" :size="40" />
      <p>{{ t('history.no_profile') }}</p>
      <RouterLink to="/" class="sa-hist__cta">{{ t('history.start_learning') }}</RouterLink>
    </div>

    <p v-else-if="loading" class="sa-hist__note" role="status">{{ t('common.loading') }}</p>

    <div v-else-if="error" class="sa-card sa-hist__empty">
      <p>{{ t('history.load_error') }}</p>
      <RouterLink to="/" class="sa-hist__cta">{{ t('common.back') }}</RouterLink>
    </div>

    <div v-else-if="items.length === 0" class="sa-card sa-hist__empty">
      <SaIcon name="sparkle" :size="40" />
      <p>{{ t('history.empty') }}</p>
      <RouterLink to="/" class="sa-hist__cta">{{ t('history.start_learning') }}</RouterLink>
    </div>

    <ul v-else class="sa-hist__list">
      <li v-for="it in items" :key="it.request_id" class="sa-hist__li">
        <component
          :is="targetOf(it) ? 'button' : 'div'"
          type="button"
          class="sa-card sa-hist__item"
          :class="{ 'sa-hist__item--dead': !targetOf(it) }"
          :disabled="!targetOf(it)"
          @click="open(it)"
        >
          <span class="sa-hist__icon" aria-hidden="true">
            <SaIcon :name="it.mode === 'test' ? 'trophy' : 'star'" :size="22" />
          </span>
          <span class="sa-hist__body">
            <span class="sa-hist__name">{{ it.title || t('history.untitled') }}</span>
            <span class="sa-hist__meta">
              <span class="sa-hist__badge">{{ t(it.mode === 'test' ? 'history.mode_test' : 'history.mode_study') }}</span>
              <span v-if="it.subject" class="sa-hist__sub">{{ humanizeSubject(it.subject) }}</span>
              <span v-if="it.status === 'generating' || it.status === 'queued'" class="sa-hist__status sa-hist__status--gen">{{ t('history.in_progress') }}</span>
              <span v-else-if="it.status === 'error'" class="sa-hist__status sa-hist__status--err">{{ t('history.failed') }}</span>
              <span class="sa-hist__date">{{ dateFmt(it.created_at) }}</span>
            </span>
          </span>
          <SaIcon v-if="targetOf(it)" name="back" :size="18" class="sa-hist__chevron" aria-hidden="true" />
        </component>
        <!-- Review a completed quiz — only when there's actually a graded attempt to review. -->
        <RouterLink
          v-if="it.mode === 'test' && it.status === 'ready' && it.attempted"
          :to="{ name: 'review', params: { sessionId: it.request_id } }"
          class="sa-hist__review"
        >
          <SaIcon name="books" :size="16" aria-hidden="true" />
          {{ t('results.review') }}
        </RouterLink>
      </li>
    </ul>

    <RouterLink to="/" class="sa-hist__home">{{ t('common.back') }}</RouterLink>
  </section>
</template>

<style scoped>
.sa-hist {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.75rem 0 3rem;
}
.sa-hist__title {
  text-align: center;
  font-size: 1.5rem;
  font-weight: 800;
}
.sa-hist__note {
  text-align: center;
  color: var(--color-ink-soft);
}
.sa-hist__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 1.75rem 1.1rem;
  text-align: center;
  color: var(--color-ink-soft);
}
.sa-hist__cta {
  min-height: var(--tap-min);
  display: inline-flex;
  align-items: center;
  font-weight: 700;
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.sa-hist__list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  list-style: none;
  margin: 0;
  padding: 0;
}
.sa-hist__li {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.sa-hist__review {
  align-self: flex-end;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-height: var(--tap-min);
  padding: 0.2rem 0.5rem;
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.sa-hist__item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.85rem 0.95rem;
  min-height: var(--tap-min);
  text-align: left;
  cursor: pointer;
  border: 2px solid var(--color-line);
  transition: border-color 0.12s ease, transform 0.12s ease;
}
@media (hover: hover) {
  .sa-hist__item:not(.sa-hist__item--dead):hover {
    border-color: var(--color-primary);
    transform: translateY(-1px);
  }
}
.sa-hist__item--dead {
  cursor: default;
  opacity: 0.7;
}
.sa-hist__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
  color: var(--color-primary);
}
.sa-hist__body {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  flex: 1;
}
.sa-hist__name {
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-hist__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: var(--color-ink-soft);
}
.sa-hist__badge {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-hist__sub {
  text-transform: capitalize;
}
.sa-hist__status {
  font-weight: 700;
}
.sa-hist__status--gen {
  color: var(--color-primary-strong);
}
.sa-hist__status--err {
  color: var(--color-coral);
}
.sa-hist__date {
  margin-left: auto;
}
.sa-hist__chevron {
  flex-shrink: 0;
  transform: rotate(180deg);
  color: var(--color-ink-soft);
}
.sa-hist__home {
  align-self: center;
  min-height: var(--tap-min);
  display: inline-flex;
  align-items: center;
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
:root[data-reduced-motion='true'] .sa-hist__item {
  transition: none;
}
</style>

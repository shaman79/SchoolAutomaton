<script setup lang="ts">
/**
 * A compact, tappable list of suggested lessons/quizzes (reuse over regeneration). Fed by
 * GET /profiles/me/recommendations and shown after finishing a session ("more like this") or on the
 * home screen ("pick up where you left off"). Mobile-first; each card is a >=44px tap target and
 * navigation mirrors the history list (ready → lesson/test, still-building → loading).
 *
 * Renders nothing when there are no items, so callers can drop it in unconditionally.
 */
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import SaIcon from '@/components/common/SaIcon.vue'
import { humanizeSubject } from '@/lib/format'
import type { LearningSessionSummary } from '@/types/session'

withDefaults(
  defineProps<{
    items: LearningSessionSummary[]
    title: string
    /** Optional hint line under the title (e.g. a gentle "try one of these" nudge). */
    hint?: string | null
  }>(),
  { hint: null },
)

const { t } = useI18n()
const router = useRouter()

function targetOf(it: LearningSessionSummary) {
  if (it.status === 'generating' || it.status === 'queued') {
    return { name: 'loading', params: { sessionId: it.request_id } }
  }
  if (it.status === 'ready') {
    return { name: it.mode === 'test' ? 'test' : 'lesson', params: { sessionId: it.request_id } }
  }
  return null
}

function open(it: LearningSessionSummary) {
  const to = targetOf(it)
  if (to) router.push(to)
}
</script>

<template>
  <section v-if="items.length" class="sa-sugg" aria-labelledby="sa-sugg-title">
    <h2 id="sa-sugg-title" class="sa-sugg__title">{{ title }}</h2>
    <p v-if="hint" class="sa-sugg__hint">{{ hint }}</p>

    <ul class="sa-sugg__list">
      <li v-for="it in items" :key="it.request_id">
        <button
          type="button"
          class="sa-card sa-sugg__item"
          :disabled="!targetOf(it)"
          @click="open(it)"
        >
          <span class="sa-sugg__icon" aria-hidden="true">
            <SaIcon :name="it.mode === 'test' ? 'trophy' : 'star'" :size="20" />
          </span>
          <span class="sa-sugg__body">
            <span class="sa-sugg__name">{{ it.title || t('history.untitled') }}</span>
            <span class="sa-sugg__meta">
              <span class="sa-sugg__badge">{{
                t(it.mode === 'test' ? 'history.mode_test' : 'history.mode_study')
              }}</span>
              <span v-if="it.subject" class="sa-sugg__sub">{{ humanizeSubject(it.subject) }}</span>
            </span>
          </span>
          <SaIcon name="back" :size="16" class="sa-sugg__chevron" aria-hidden="true" />
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.sa-sugg {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-sugg__title {
  font-size: 1.05rem;
  font-weight: 700;
}
.sa-sugg__hint {
  margin: -0.35rem 0 0;
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-sugg__list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  list-style: none;
  margin: 0;
  padding: 0;
}
.sa-sugg__item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.7rem 0.85rem;
  min-height: var(--tap-min);
  text-align: left;
  cursor: pointer;
  border: 2px solid var(--color-line);
  transition: border-color 0.12s ease, transform 0.12s ease;
}
@media (hover: hover) {
  .sa-sugg__item:not(:disabled):hover {
    border-color: var(--color-primary);
    transform: translateY(-1px);
  }
}
.sa-sugg__item:disabled {
  cursor: default;
  opacity: 0.7;
}
.sa-sugg__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 2.1rem;
  height: 2.1rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
  color: var(--color-primary);
}
.sa-sugg__body {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
  flex: 1;
}
.sa-sugg__name {
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-sugg__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.76rem;
  color: var(--color-ink-soft);
}
.sa-sugg__badge {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-sugg__sub {
  text-transform: capitalize;
}
.sa-sugg__chevron {
  flex-shrink: 0;
  transform: rotate(180deg);
  color: var(--color-ink-soft);
}
:root[data-reduced-motion='true'] .sa-sugg__item {
  transition: none;
}
</style>

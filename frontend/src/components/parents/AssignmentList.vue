<script setup lang="ts">
/**
 * The tasks a parent gave, as compact rows: the topic, its kind, and where it is — being prepared,
 * waiting to be opened, in progress (part / question N of M), couldn't be prepared ("Try again", the
 * one action that needs doing, stays visible). Finished tasks fold into "Done (n)" with their result.
 * Everything else a row can do sits behind its "⋯": take a task back (asks first, inline) or give a
 * finished one again. Every state is an icon + words, never colour alone.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import SaIcon, { type IconName } from '@/components/common/SaIcon.vue'
import SaMenu, { type MenuItem } from '@/components/common/SaMenu.vue'
import { toast } from '@/components/common/useToasts'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/apiError'
import { parentErrorKey } from '@/lib/errors'
import { dayLabel, progressLabel } from '@/lib/format'
import type { Assignment, AssignmentStatus } from '@/types/session'

const props = defineProps<{ code: string; tasks: Assignment[] }>()
const emit = defineEmits<{
  (e: 'removed', id: number): void
  (e: 'updated', task: Assignment): void
  (e: 'again', task: Assignment): void
  (e: 'revoked'): void
}>()

const { t } = useI18n()

const busyId = ref<number | null>(null)
const confirmId = ref<number | null>(null)

const open = computed(() => props.tasks.filter((a) => a.status !== 'done'))
const done = computed(() => props.tasks.filter((a) => a.status === 'done'))

const ICON: Record<AssignmentStatus, IconName> = {
  preparing: 'clock',
  ready: 'clock',
  started: 'books',
  done: 'check',
  failed: 'hint',
}

function statusText(a: Assignment): string {
  switch (a.status) {
    case 'started':
      return t('parent.status.started', { progress: progressLabel(a) ?? '' })
    case 'ready': {
      const when = dayLabel(a.created_at)
      return when ? `${t('parent.status.ready')} · ${t('parent.given_on', { when })}` : t('parent.status.ready')
    }
    case 'done': {
      // "Done today · 4 of 5 correct"
      const when = dayLabel(a.progress?.last_active_at)
      const base = when ? t('parent.status.done_when', { when }) : t('parent.status.done')
      return a.result
        ? `${base} · ${t('parent.status.result', { correct: a.result.correct, total: a.result.total })}`
        : base
    }
    default:
      return t(`parent.status.${a.status}`)
  }
}

function menu(a: Assignment): MenuItem[] {
  const items: MenuItem[] = []
  if (a.status === 'done') items.push({ label: t('parent.assign_again'), action: () => emit('again', a) })
  items.push(
    a.status === 'done'
      ? { label: t('parent.remove_done'), action: () => void remove(a), danger: true }
      : { label: t('parent.remove'), action: () => (confirmId.value = a.id), danger: true },
  )
  return items
}

function failed(e: unknown): void {
  if (e instanceof ApiError && e.status === 401) emit('revoked')
  else toast.error(t(parentErrorKey(e)))
}

async function retry(a: Assignment): Promise<void> {
  if (busyId.value !== null) return
  busyId.value = a.id
  try {
    emit('updated', await api.parentRetryAssignment(props.code, a.id))
  } catch (e) {
    failed(e)
  } finally {
    busyId.value = null
  }
}

async function remove(a: Assignment): Promise<void> {
  if (busyId.value !== null) return
  busyId.value = a.id
  try {
    await api.parentRemoveAssignment(props.code, a.id)
    confirmId.value = null
    emit('removed', a.id)
    toast.info(t('parent.removed'))
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) emit('removed', a.id) // already gone
    else failed(e)
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <div class="sa-alist">
    <ul v-if="open.length" class="sa-alist__rows">
      <li v-for="a in open" :key="a.id" class="sa-alist__row" :data-status="a.status">
        <div class="sa-alist__line">
          <div class="sa-alist__main">
            <p class="sa-alist__name">
              {{ a.title || t('history.untitled') }}
              <span class="sa-alist__badge">{{ t(a.mode === 'test' ? 'parent.mode_test' : 'parent.mode_study') }}</span>
            </p>
            <p class="sa-alist__status">
              <SaIcon :name="ICON[a.status]" :size="16" />
              <span>{{ statusText(a) }}</span>
            </p>
          </div>
          <SaMenu :items="menu(a)" :label="t('parent.more_for', { name: a.title })" />
        </div>
        <SaButton
          v-if="a.status === 'failed' && confirmId !== a.id"
          variant="primary"
          size="sm"
          icon="sparkle"
          class="sa-alist__retry"
          :loading="busyId === a.id"
          @click="retry(a)"
        >
          {{ t('parent.retry') }}
        </SaButton>
        <div v-if="confirmId === a.id" class="sa-alist__confirm" role="group" :aria-label="t('parent.remove_confirm')">
          <p>{{ t('parent.remove_confirm') }}</p>
          <div class="sa-alist__actions">
            <SaButton variant="primary" size="sm" :loading="busyId === a.id" @click="remove(a)">
              {{ t('parent.remove') }}
            </SaButton>
            <SaButton variant="ghost" size="sm" :disabled="busyId === a.id" @click="confirmId = null">
              {{ t('parent.keep') }}
            </SaButton>
          </div>
        </div>
      </li>
    </ul>

    <!-- Finished: kept for the result, but out of the way -->
    <details v-if="done.length" class="sa-alist__done" :open="!open.length">
      <summary class="sa-alist__summary">{{ t('parent.done_group', { n: done.length }) }}</summary>
      <ul class="sa-alist__rows">
        <li v-for="a in done" :key="a.id" class="sa-alist__row" data-status="done">
          <div class="sa-alist__line">
            <div class="sa-alist__main">
              <p class="sa-alist__name">
                {{ a.title || t('history.untitled') }}
                <span class="sa-alist__badge">{{ t(a.mode === 'test' ? 'parent.mode_test' : 'parent.mode_study') }}</span>
              </p>
              <p class="sa-alist__status">
                <SaIcon name="check" :size="16" />
                <span>{{ statusText(a) }}</span>
              </p>
            </div>
            <SaMenu :items="menu(a)" :label="t('parent.more_for', { name: a.title })" />
          </div>
        </li>
      </ul>
    </details>
  </div>
</template>

<style scoped>
.sa-alist {
  display: flex;
  flex-direction: column;
}
.sa-alist__rows {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-alist__row {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.7rem 0;
}
.sa-alist__row + .sa-alist__row {
  border-top: 1px solid var(--color-line);
}
.sa-alist__line {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
}
.sa-alist__main {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  flex: 1;
  min-width: 0;
  padding-top: 0.2rem;
}
.sa-alist__name {
  margin: 0;
  font-weight: 800;
  line-height: 1.3;
  overflow-wrap: break-word;
}
.sa-alist__badge {
  display: inline-block;
  margin-left: 0.3rem;
  padding: 0 0.4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  vertical-align: 0.1em;
}
.sa-alist__status {
  display: flex;
  align-items: flex-start;
  gap: 0.35rem;
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.4;
  color: var(--color-ink-soft);
}
.sa-alist__status :deep(svg) {
  margin-top: 0.15rem;
}
.sa-alist__row[data-status='failed'] .sa-alist__status {
  color: var(--color-ink);
  font-weight: 600;
}
.sa-alist__row[data-status='done'] .sa-alist__status {
  color: var(--color-primary-strong);
  font-weight: 600;
}
.sa-alist__retry {
  align-self: flex-start;
}
.sa-alist__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.sa-alist__confirm {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  border-radius: var(--radius-btn);
  background: color-mix(in srgb, var(--color-sun) 14%, var(--color-surface));
  border: 1px solid color-mix(in srgb, var(--color-sun) 45%, var(--color-line));
}
.sa-alist__confirm p {
  margin: 0;
}
.sa-alist__done {
  border-top: 1px solid var(--color-line);
}
.sa-alist__rows + .sa-alist__done {
  margin-top: 0.15rem;
}
.sa-alist__summary {
  display: flex;
  align-items: center;
  min-height: var(--tap-min);
  font-weight: 700;
  color: var(--color-ink-soft);
  cursor: pointer;
  list-style: none;
}
.sa-alist__summary::-webkit-details-marker {
  display: none;
}
.sa-alist__summary::after {
  content: '';
  margin-left: auto;
  margin-right: 0.9rem;
  width: 0.5rem;
  height: 0.5rem;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(45deg);
}
.sa-alist__done[open] .sa-alist__summary::after {
  transform: rotate(-135deg);
}
.sa-alist__summary:focus-visible {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
  border-radius: 4px;
}
</style>

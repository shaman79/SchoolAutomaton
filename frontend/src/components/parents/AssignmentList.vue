<script setup lang="ts">
/**
 * The tasks a parent gave (newest first) with where each one is: being prepared, waiting to be
 * opened, in progress (part / question N of M), done (a quiz with its score), or couldn't be prepared
 * (with "Try again"). Every state is an icon + words, never colour alone. A task can be taken back
 * (it leaves the child's home screen) after an inline "are you sure".
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import SaIcon, { type IconName } from '@/components/common/SaIcon.vue'
import { toast } from '@/components/common/useToasts'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/apiError'
import { parentErrorKey } from '@/lib/errors'
import { dayLabel, progressLabel, subjectLabel } from '@/lib/format'
import type { Assignment, AssignmentStatus } from '@/types/session'

const props = defineProps<{ code: string; tasks: Assignment[] }>()
const emit = defineEmits<{
  (e: 'removed', id: number): void
  (e: 'updated', task: Assignment): void
  (e: 'revoked'): void
}>()

const { t } = useI18n()

const busyId = ref<number | null>(null)
const confirmId = ref<number | null>(null)

const ICON: Record<AssignmentStatus, IconName> = {
  preparing: 'clock',
  ready: 'clock',
  started: 'books',
  done: 'check',
  failed: 'hint',
}

function statusText(a: Assignment): string {
  if (a.status === 'started') {
    return t('parent.status.started', { progress: progressLabel(a) ?? '' })
  }
  if (a.status === 'done') {
    // "Done today · 4 of 5 correct"
    const when = dayLabel(a.progress?.last_active_at)
    const done = when ? t('parent.status.done_when', { when }) : t('parent.status.done')
    return a.result
      ? `${done} · ${t('parent.status.result', { correct: a.result.correct, total: a.result.total })}`
      : done
  }
  return t(`parent.status.${a.status}`)
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
    if (e instanceof ApiError && e.status === 404) {
      emit('removed', a.id) // already gone
    } else {
      failed(e)
    }
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <ul class="sa-alist">
    <li v-for="a in tasks" :key="a.id" class="sa-alist__item" :data-status="a.status">
      <p class="sa-alist__name">{{ a.title || t('history.untitled') }}</p>
      <p class="sa-alist__meta">
        <span class="sa-alist__badge">{{ t(a.mode === 'test' ? 'parent.mode_test' : 'parent.mode_study') }}</span>
        <span v-if="a.subject">{{ subjectLabel(a.subject) }}</span>
        <span v-if="a.created_at">· {{ t('parent.given_on', { when: dayLabel(a.created_at) }) }}</span>
      </p>
      <p class="sa-alist__status">
        <SaIcon :name="ICON[a.status]" :size="18" />
        <span>{{ statusText(a) }}</span>
      </p>

      <div v-if="confirmId === a.id" class="sa-alist__confirm" role="alertdialog" :aria-label="t('parent.remove_confirm')">
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
      <div v-else class="sa-alist__actions">
        <SaButton
          v-if="a.status === 'failed'"
          variant="primary"
          size="sm"
          icon="sparkle"
          :loading="busyId === a.id"
          @click="retry(a)"
        >
          {{ t('parent.retry') }}
        </SaButton>
        <SaButton
          variant="subtle"
          size="sm"
          icon="x"
          :aria-label="`${a.status === 'done' ? t('parent.remove_done') : t('parent.remove')}: ${a.title}`"
          :disabled="busyId !== null"
          @click="a.status === 'done' ? remove(a) : (confirmId = a.id)"
        >
          {{ a.status === 'done' ? t('parent.remove_done') : t('parent.remove') }}
        </SaButton>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.sa-alist {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-alist__item {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.85rem 0;
}
.sa-alist__item:first-child {
  padding-top: 0.25rem;
}
.sa-alist__item + .sa-alist__item {
  border-top: 1px solid var(--color-line);
}
.sa-alist__name {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 800;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.sa-alist__meta {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-alist__badge {
  font-size: 0.74rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-alist__status {
  display: flex;
  align-items: flex-start;
  gap: 0.4rem;
  margin: 0;
  font-weight: 600;
  line-height: 1.4;
}
.sa-alist__status :deep(svg) {
  margin-top: 0.12rem;
}
.sa-alist__item[data-status='done'] .sa-alist__status {
  color: var(--color-primary-strong);
}
.sa-alist__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.15rem;
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
</style>

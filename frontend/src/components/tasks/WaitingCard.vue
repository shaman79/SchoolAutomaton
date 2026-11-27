<script setup lang="ts">
/**
 * Home: the tasks a parent gave that aren't finished yet, in ONE compact list at the top — they are
 * what is genuinely waiting, and the card goes away once they are done (or the parent takes them
 * back). The learner's own unfinished lesson/quiz is not here: it is a quiet row below the box for
 * something new (ContinueRow). Each row is a single tap: what it is, how far they are, and what
 * tapping does ("Continue" / "Start" / "Getting ready…"). A ready task opens the lesson/quiz; one
 * still being prepared — or that couldn't be — goes through the loading screen, which waits for it or
 * tries again. Started ones come first, then in the order given. Three rows show; the rest fold away,
 * so the box for something new stays in reach.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import { displayTitle, progressLabel, subjectLabel } from '@/lib/format'
import type { Assignment, Mode, SessionProgress } from '@/types/session'

const props = defineProps<{ tasks: Assignment[] }>()

const { t } = useI18n()

interface Row {
  key: string
  title: string
  mode: Mode
  subject: string | null
  progress: SessionProgress | null
  kind: 'continue' | 'start' | 'preparing' | 'failed'
  to: { name: string; params: { sessionId: string } }
}

function open(mode: Mode, sessionId: string) {
  return { name: mode === 'test' ? 'test' : 'lesson', params: { sessionId } }
}

const rows = computed<Row[]>(() => {
  const started: Row[] = []
  const rest: Row[] = []
  for (const a of props.tasks) {
    const base = {
      key: `t-${a.id}`,
      title: displayTitle(a.title) || t('history.untitled'),
      mode: a.mode,
      subject: a.subject,
      progress: null,
    }
    if (a.status === 'started') {
      started.push({ ...base, progress: a.progress, kind: 'continue', to: open(a.mode, a.request_id) })
    } else if (a.status === 'ready') {
      rest.push({ ...base, kind: 'start', to: open(a.mode, a.request_id) })
    } else {
      rest.push({
        ...base,
        kind: a.status === 'preparing' ? 'preparing' : 'failed',
        to: { name: 'loading', params: { sessionId: a.request_id } },
      })
    }
  }
  return [...started, ...rest]
})

const FOLDED = 3
const expanded = ref(false)
const shown = computed(() => (expanded.value ? rows.value : rows.value.slice(0, FOLDED)))
const hidden = computed(() => rows.value.length - FOLDED)

function action(r: Row): string {
  if (r.kind === 'continue') return t('common.continue')
  if (r.kind === 'preparing') return t('tasks.preparing')
  return t('tasks.start')
}
function percent(p: SessionProgress): number {
  return p.total ? Math.round((Math.min(p.position, p.total) / p.total) * 100) : 0
}
</script>

<template>
  <section v-if="rows.length" class="sa-card sa-wait" aria-labelledby="sa-wait-title">
    <h2 id="sa-wait-title" class="sa-wait__title">
      <SaIcon name="users" :size="16" />{{ t('tasks.waiting_title') }}
    </h2>
    <ul class="sa-wait__list">
      <li v-for="r in shown" :key="r.key">
        <RouterLink :to="r.to" class="sa-wait__row" :data-kind="r.kind">
          <span class="sa-wait__main">
            <span class="sa-wait__name">{{ r.title }}</span>
            <span class="sa-wait__meta">
              <span class="sa-wait__badge">{{ t(r.mode === 'test' ? 'history.mode_test' : 'history.mode_study') }}</span>
              <span v-if="r.progress">{{ progressLabel({ mode: r.mode, progress: r.progress }) }}</span>
              <span v-else-if="r.kind === 'failed'">{{ t('tasks.failed_hint') }}</span>
              <span v-else-if="r.subject">{{ subjectLabel(r.subject) }}</span>
            </span>
            <span v-if="r.progress" class="sa-wait__bar" aria-hidden="true">
              <span :style="{ width: `${percent(r.progress)}%` }" />
            </span>
          </span>
          <span class="sa-wait__action">
            {{ action(r) }}
            <SaIcon :name="r.kind === 'preparing' ? 'clock' : 'back'" :size="16" class="sa-wait__chevron" />
          </span>
        </RouterLink>
      </li>
    </ul>
    <SaButton
      v-if="hidden > 0"
      variant="subtle"
      size="sm"
      class="sa-wait__more"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ expanded ? t('tasks.less') : t('tasks.more', { n: hidden }) }}
    </SaButton>
  </section>
</template>

<style scoped>
.sa-wait {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.9rem 0.6rem 0.6rem;
  border: 2px solid color-mix(in srgb, var(--color-primary) 40%, var(--color-line));
}
.sa-wait__title {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0 0.5rem 0.15rem;
  font-size: 0.8rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-primary-strong);
}
.sa-wait__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-wait__list li + li {
  border-top: 1px solid var(--color-line);
}
/* The whole row is the target: at least 44px, its action word at the end. */
.sa-wait__row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 3.5rem;
  padding: 0.6rem 0.5rem;
  border-radius: var(--radius-btn);
  color: var(--color-ink);
  text-decoration: none;
}
.sa-wait__row:hover {
  background: var(--color-surface-2);
}
.sa-wait__row:focus-visible {
  outline: 3px solid var(--color-primary);
  outline-offset: 1px;
}
.sa-wait__main {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  flex: 1;
  min-width: 0;
}
.sa-wait__name {
  font-size: 1.05rem;
  font-weight: 800;
  line-height: 1.25;
  overflow-wrap: break-word;
}
.sa-wait__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 0.45rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-wait__badge {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0 0.4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-wait__bar {
  display: block;
  height: 0.3rem;
  margin-top: 0.15rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
  overflow: hidden;
}
.sa-wait__bar > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
}
.sa-wait__action {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  flex: none;
  font-weight: 800;
  color: var(--color-primary-strong);
}
.sa-wait__row[data-kind='preparing'] .sa-wait__action {
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-wait__chevron {
  transform: rotate(180deg);
}
.sa-wait__row[data-kind='preparing'] .sa-wait__chevron {
  transform: none;
}
.sa-wait__more {
  align-self: center;
}
</style>

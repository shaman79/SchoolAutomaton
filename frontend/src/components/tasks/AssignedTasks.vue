<script setup lang="ts">
/**
 * Home: the tasks a parent gave that aren't finished yet ("Tasks from your parents"), in the order
 * they were given. Each opens with one tap: a ready task goes straight to the lesson/quiz (an
 * unfinished one resumes where the child left off); one still being prepared — or that couldn't be —
 * goes through the loading screen, which waits for it or tries again. The first few show; the rest
 * fold away behind "Show all", so the prompt box stays in reach on a phone.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import ProgressBar from '@/components/common/ProgressBar.vue'
import SaButton from '@/components/common/SaButton.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import { progressLabel, subjectLabel } from '@/lib/format'
import type { Assignment } from '@/types/session'

const props = defineProps<{ tasks: Assignment[] }>()

const { t } = useI18n()

const FOLDED = 3
const expanded = ref(false)
const shown = computed(() => (expanded.value ? props.tasks : props.tasks.slice(0, FOLDED)))
const hidden = computed(() => props.tasks.length - shown.value.length)

function target(a: Assignment) {
  if (a.status === 'ready' || a.status === 'started') {
    return { name: a.mode === 'test' ? 'test' : 'lesson', params: { sessionId: a.request_id } }
  }
  return { name: 'loading', params: { sessionId: a.request_id } }
}

function actionLabel(a: Assignment): string {
  if (a.status === 'started') return t('common.continue')
  if (a.status === 'preparing') return t('tasks.preparing')
  return t('tasks.start')
}
</script>

<template>
  <section v-if="tasks.length" class="sa-card sa-tasks" aria-labelledby="sa-tasks-title">
    <h2 id="sa-tasks-title" class="sa-tasks__title">
      <SaIcon name="users" :size="20" />
      {{ t('tasks.title') }}
    </h2>
    <ul class="sa-tasks__list">
      <li v-for="a in shown" :key="a.id" class="sa-tasks__item">
        <p class="sa-tasks__name">{{ a.title || t('history.untitled') }}</p>
        <p class="sa-tasks__meta">
          <span class="sa-tasks__badge">{{ t(a.mode === 'test' ? 'history.mode_test' : 'history.mode_study') }}</span>
          <span v-if="a.subject">{{ subjectLabel(a.subject) }}</span>
          <span v-if="a.status === 'started' && a.progress">· {{ progressLabel(a) }}</span>
        </p>
        <ProgressBar
          v-if="a.status === 'started' && a.progress"
          :value="a.progress.position"
          :max="a.progress.total"
          size="sm"
          :label="a.title || t('history.untitled')"
          :value-text="progressLabel(a) ?? undefined"
        />
        <p v-if="a.status === 'failed'" class="sa-tasks__hint">{{ t('tasks.failed_hint') }}</p>
        <SaButton
          :variant="a.status === 'preparing' ? 'ghost' : 'primary'"
          block
          :icon="a.status === 'preparing' ? 'clock' : 'sparkle'"
          icon-right
          :to="target(a)"
        >
          {{ actionLabel(a) }}
        </SaButton>
      </li>
    </ul>
    <SaButton
      v-if="hidden > 0 || expanded"
      variant="subtle"
      size="sm"
      class="sa-tasks__more"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ expanded ? t('tasks.show_less') : t('tasks.show_all', { n: tasks.length }) }}
    </SaButton>
  </section>
</template>

<style scoped>
.sa-tasks {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.1rem;
  border: 2px solid var(--color-accent);
}
.sa-tasks__title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin: 0;
  font-size: 0.8rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-primary-strong);
}
.sa-tasks__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sa-tasks__item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 0;
}
.sa-tasks__item:first-child {
  padding-top: 0;
}
.sa-tasks__item + .sa-tasks__item {
  border-top: 1px solid var(--color-line);
}
.sa-tasks__name {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 800;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.sa-tasks__meta {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-tasks__badge {
  font-size: 0.76rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-tasks__hint {
  margin: 0;
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-tasks__more {
  align-self: center;
}
</style>

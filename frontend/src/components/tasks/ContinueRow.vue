<script setup lang="ts">
/**
 * Home: the lesson/quiz the learner was last in, as one quiet row below the box for something new —
 * what it is, how far they got, one tap to carry on exactly there. Not an obligation: the learner can
 * hide it (×, on this device, until they work on it again — see lib/hiddenContinue); a short note
 * then says where it still is ("My lessons") and takes the focus, so a keyboard or screen-reader
 * user isn't dropped at the top of the page. The server offers only something touched lately.
 */
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaIcon from '@/components/common/SaIcon.vue'
import { displayTitle, progressLabel } from '@/lib/format'
import { hideContinue } from '@/lib/hiddenContinue'
import type { LearningSessionSummary } from '@/types/session'

const props = defineProps<{ session: LearningSessionSummary }>()

const { t } = useI18n()

const title = computed(() => displayTitle(props.session.title) || t('history.untitled'))
const to = computed(() => ({
  name: props.session.mode === 'test' ? 'test' : 'lesson',
  params: { sessionId: props.session.request_id },
}))
const percent = computed(() => {
  const p = props.session.progress
  return p?.total ? Math.round((Math.min(p.position, p.total) / p.total) * 100) : 0
})

const hidden = ref(false)
const note = ref<HTMLElement | null>(null)
async function hide() {
  hideContinue(props.session)
  hidden.value = true
  await nextTick()
  note.value?.focus()
}
</script>

<template>
  <section v-if="!hidden" class="sa-card sa-cont" :aria-label="t('tasks.continue_label')">
    <RouterLink :to="to" class="sa-cont__link">
      <span class="sa-cont__main">
        <span class="sa-cont__eyebrow">{{ t('tasks.continue_label') }}</span>
        <span class="sa-cont__name">{{ title }}</span>
        <span class="sa-cont__meta">
          <span class="sa-cont__badge">{{ t(session.mode === 'test' ? 'history.mode_test' : 'history.mode_study') }}</span>
          <span v-if="session.progress">{{ progressLabel(session) }}</span>
        </span>
        <span v-if="session.progress" class="sa-cont__bar" aria-hidden="true">
          <span :style="{ width: `${percent}%` }" />
        </span>
      </span>
      <span class="sa-cont__action">
        {{ t('common.continue') }}
        <SaIcon name="back" :size="16" class="sa-cont__chevron" />
      </span>
    </RouterLink>
    <button
      type="button"
      class="sa-cont__hide"
      :aria-label="t('tasks.hide_continue', { title })"
      :title="t('tasks.hide_continue', { title })"
      @click="hide"
    >
      <SaIcon name="x" :size="18" />
    </button>
  </section>
  <p v-else ref="note" class="sa-cont__note" tabindex="-1" role="status">
    {{ t('tasks.hidden_note') }}
    <RouterLink :to="{ name: 'history' }" class="sa-cont__note-link">{{ t('history.title') }}</RouterLink>.
  </p>
</template>

<style scoped>
.sa-cont {
  display: flex;
  align-items: stretch;
  gap: 0.25rem;
  padding: 0.35rem;
}
/* The whole row is the target (≥44px), its action word at the end; × sits apart from it. */
.sa-cont__link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex: 1;
  min-width: 0;
  min-height: 3.25rem;
  padding: 0.5rem 0.6rem;
  border-radius: var(--radius-btn);
  color: var(--color-ink);
  text-decoration: none;
}
.sa-cont__link:hover {
  background: var(--color-surface-2);
}
.sa-cont__link:focus-visible,
.sa-cont__hide:focus-visible {
  outline: 3px solid var(--color-primary);
  outline-offset: 1px;
}
.sa-cont__main {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  flex: 1;
  min-width: 0;
}
.sa-cont__eyebrow {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--color-ink-soft);
}
.sa-cont__name {
  font-weight: 800;
  line-height: 1.25;
  overflow-wrap: break-word;
}
.sa-cont__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 0.45rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-cont__badge {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0 0.4rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-cont__bar {
  display: block;
  height: 0.25rem;
  margin-top: 0.1rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
  overflow: hidden;
}
.sa-cont__bar > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
}
.sa-cont__action {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  flex: none;
  font-weight: 800;
  color: var(--color-primary-strong);
}
.sa-cont__chevron {
  transform: rotate(180deg);
}
.sa-cont__hide {
  display: grid;
  place-items: center;
  flex: none;
  width: var(--tap-min);
  min-height: var(--tap-min);
  border: 0;
  border-radius: var(--radius-btn);
  background: none;
  color: var(--color-ink-soft);
  cursor: pointer;
}
.sa-cont__hide:hover {
  background: var(--color-surface-2);
  color: var(--color-ink);
}
.sa-cont__note {
  margin: 0;
  padding: 0 0.25rem;
  font-size: 0.9rem;
  color: var(--color-ink-soft);
}
.sa-cont__note:focus {
  outline: none;
}
.sa-cont__note-link {
  display: inline-flex;
  align-items: center;
  min-height: var(--tap-min);
  font-weight: 700;
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>

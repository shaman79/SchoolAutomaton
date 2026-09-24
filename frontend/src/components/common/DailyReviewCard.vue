<script setup lang="ts">
/**
 * Entry card into today's spaced-repetition round ("Zalij svou zahrádku"). Loads the learner's due
 * items itself and renders NOTHING when there is no profile, nothing is due, or the load fails — so
 * callers (home, progress) can drop it in unconditionally. Shows a capped count of waiting questions.
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaIcon from '@/components/common/SaIcon.vue'
import { api } from '@/lib/api'
import { useSessionStore } from '@/stores/session'

/** Same size as one review round (DailyReviewView), so the promise matches what the round delivers. */
const ROUND_SIZE = 10

const { t } = useI18n()
const session = useSessionStore()
const due = ref(0)

onMounted(async () => {
  if (!session.resumeCode) return
  try {
    due.value = (await api.getDue(ROUND_SIZE)).items.length
  } catch {
    /* optional entry point — stay hidden */
  }
})
</script>

<template>
  <RouterLink v-if="due > 0" :to="{ name: 'daily' }" class="sa-card sa-daily-card">
    <span class="sa-daily-card__icon" aria-hidden="true">💧</span>
    <span class="sa-daily-card__body">
      <span class="sa-daily-card__title">{{ t('daily.title') }}</span>
      <span class="sa-daily-card__sub">{{ t('daily.cta_count', { n: due }, due) }}</span>
    </span>
    <SaIcon name="back" :size="16" class="sa-daily-card__chevron" aria-hidden="true" />
  </RouterLink>
</template>

<style scoped>
.sa-daily-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0.9rem;
  min-height: var(--tap-min);
  border: 2px solid color-mix(in srgb, var(--color-sky) 55%, var(--color-line));
  background: color-mix(in srgb, var(--color-sky) 10%, var(--color-surface));
  color: var(--color-ink);
  transition: transform 0.12s ease;
}
@media (hover: hover) {
  .sa-daily-card:hover {
    transform: translateY(-1px);
  }
}
.sa-daily-card__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 2.3rem;
  height: 2.3rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface);
  font-size: 1.2rem;
}
.sa-daily-card__body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.sa-daily-card__title {
  font-weight: 800;
}
.sa-daily-card__sub {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-daily-card__chevron {
  flex-shrink: 0;
  transform: rotate(180deg);
  color: var(--color-ink-soft);
}
:root[data-reduced-motion='true'] .sa-daily-card {
  transition: none;
}
</style>

<script setup lang="ts">
/**
 * "We can't reach the server" — shown while the learner's profile can't be loaded (offline, server
 * restarting). Reassures that their progress is safe (the resume code is kept) and offers Retry; it
 * also retries by itself when the device comes back online. Disappears as soon as the profile loads.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from './SaButton.vue'
import SaIcon from './SaIcon.vue'
import { useSessionStore } from '@/stores/session'

const { t } = useI18n()
const session = useSessionStore()
const busy = ref(false)

async function retry() {
  if (busy.value) return
  busy.value = true
  try {
    await session.reconnect()
  } finally {
    busy.value = false
  }
}

function onOnline() {
  if (session.unreachable) void retry()
}
onMounted(() => window.addEventListener('online', onOnline))
onBeforeUnmount(() => window.removeEventListener('online', onOnline))
</script>

<template>
  <div v-if="session.unreachable" class="sa-card sa-conn" role="alert">
    <span class="sa-conn__icon" aria-hidden="true"><SaIcon name="hint" :size="22" /></span>
    <div class="sa-conn__text">
      <p class="sa-conn__title">{{ t('errors.connection_title') }}</p>
      <p class="sa-conn__body">{{ t('errors.connection_body') }}</p>
    </div>
    <SaButton variant="primary" icon="sparkle" :loading="busy" class="sa-conn__btn" @click="retry">
      {{ t('common.retry') }}
    </SaButton>
  </div>
</template>

<style scoped>
.sa-conn {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem 0.75rem;
  margin-top: 0.75rem;
  padding: 0.85rem 1rem;
  /* Calm, not alarming: an outline + icon + words, never colour alone. */
  border: 2px solid var(--color-sun);
  background: color-mix(in srgb, var(--color-sun) 10%, var(--color-surface));
}
.sa-conn__icon {
  flex: none;
  display: inline-flex;
  color: var(--color-ink);
}
.sa-conn__text {
  flex: 1 1 12rem;
  min-width: 0;
}
.sa-conn__title {
  margin: 0;
  font-weight: 800;
}
.sa-conn__body {
  margin: 0.15rem 0 0;
  color: var(--color-ink-soft);
}
.sa-conn__btn {
  flex: 1 1 100%;
}
@media (min-width: 480px) {
  .sa-conn__btn {
    flex: 0 0 auto;
  }
}
</style>

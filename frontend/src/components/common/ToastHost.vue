<script setup lang="ts">
/**
 * Global toast outlet. Renders the shared toast queue inside polite/assertive
 * aria-live regions so screen readers announce them. Mounted once near the app
 * root. Toasts use icon + color + text (never color-only). Motion is gated on
 * the reduced-motion preference. Anchored at the bottom on mobile (thumb-zone),
 * top-right on larger screens, clear of safe-area insets.
 */
import { computed } from 'vue'

import { useReducedMotion } from '@/composables/useReducedMotion'

import SaIcon from './SaIcon.vue'
import { toast, toasts, type ToastTone } from './useToasts'

const { reduced } = useReducedMotion()

const polite = computed(() => toasts.items.filter((t) => t.tone !== 'error'))
const assertive = computed(() => toasts.items.filter((t) => t.tone === 'error'))

const toneClass: Record<ToastTone, string> = {
  info: 'sa-toast--info',
  success: 'sa-toast--success',
  warning: 'sa-toast--warning',
  error: 'sa-toast--error',
}
</script>

<template>
  <Teleport to="body">
    <div class="sa-toast-host safe-bottom" :class="{ 'sa-toast-host--static': reduced }">
      <div class="sa-toast-region" aria-live="polite" aria-atomic="false">
        <TransitionGroup :name="reduced ? '' : 'sa-toast'" tag="div" class="flex flex-col gap-2">
          <div
            v-for="t in polite"
            :key="t.id"
            class="sa-toast sa-card"
            :class="toneClass[t.tone]"
            role="status"
          >
            <SaIcon v-if="t.icon" :name="t.icon" :size="20" class="mt-0.5 shrink-0" />
            <span class="flex-1 text-sm font-medium">{{ t.message }}</span>
            <button
              type="button"
              class="sa-toast__close sa-tap"
              :aria-label="'Dismiss'"
              @click="toast.dismiss(t.id)"
            >
              <SaIcon name="x" :size="16" />
            </button>
          </div>
        </TransitionGroup>
      </div>
      <div class="sa-toast-region" aria-live="assertive" aria-atomic="false">
        <TransitionGroup :name="reduced ? '' : 'sa-toast'" tag="div" class="flex flex-col gap-2">
          <div
            v-for="t in assertive"
            :key="t.id"
            class="sa-toast sa-card sa-toast--error"
            role="alert"
          >
            <SaIcon v-if="t.icon" :name="t.icon" :size="20" class="mt-0.5 shrink-0" />
            <span class="flex-1 text-sm font-medium">{{ t.message }}</span>
            <button
              type="button"
              class="sa-toast__close sa-tap"
              :aria-label="'Dismiss'"
              @click="toast.dismiss(t.id)"
            >
              <SaIcon name="x" :size="16" />
            </button>
          </div>
        </TransitionGroup>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.sa-toast-host {
  position: fixed;
  inset: auto 0 0 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  pointer-events: none;
}
@media (min-width: 640px) {
  .sa-toast-host {
    inset: 0 0 auto auto;
    max-width: 24rem;
    padding-top: max(env(safe-area-inset-top), 0.75rem);
  }
}
.sa-toast {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.7rem 0.8rem;
  pointer-events: auto;
  border-left: 4px solid var(--color-primary);
}
.sa-toast--success {
  border-left-color: var(--color-mint);
}
.sa-toast--warning {
  border-left-color: var(--color-sun);
}
.sa-toast--error {
  border-left-color: var(--color-coral);
}
.sa-toast--info {
  border-left-color: var(--color-sky);
}
.sa-toast__close {
  display: inline-grid;
  place-items: center;
  border-radius: var(--radius-pill);
  color: var(--color-ink-soft);
  cursor: pointer;
}
.sa-toast__close:hover {
  background: var(--color-surface-2);
}
/* enter/leave (skipped when reduced) */
.sa-toast-enter-active,
.sa-toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.sa-toast-enter-from,
.sa-toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
.sa-toast-leave-active {
  position: absolute;
  width: calc(100% - 1.5rem);
}
</style>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterView } from 'vue-router'

import SaIcon from '@/components/common/SaIcon.vue'
import ToastHost from '@/components/common/ToastHost.vue'
import { toast } from '@/components/common/useToasts'
import AccessibilityPanel from '@/components/layout/AccessibilityPanel.vue'
import AppFooter from '@/components/layout/AppFooter.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import { useSessionStore } from '@/stores/session'

const { t } = useI18n()
const session = useSessionStore()
const panelOpen = ref(false)

// When a brand-new anonymous profile is created, nudge the learner to save their continuation code
// (they typically navigate straight into a lesson, so a sticky-ish toast catches the moment).
watch(
  () => session.lastResumeCodeForDisplay,
  (code) => {
    if (code) toast.info(t('resume.created_toast', { code }), { timeout: 12000, icon: 'sparkle' })
  },
)

/**
 * We do NOT call ensureProfile here (it's lazy at the first prompt — SPEC flow).
 * But if a resume code is already cached, best-effort hydrate the gamification
 * snapshot so the header bar shows level/streak/XP immediately. Errors (offline,
 * stale code) are swallowed; ensureProfile will fully recover later.
 */
onMounted(async () => {
  if (session.resumeCode && !session.gamification) {
    try {
      await session.refreshGamification()
    } catch {
      /* ignore — header simply hides the bar until a profile loads */
    }
  }
})
</script>

<template>
  <div class="flex min-h-dvh flex-col">
    <a href="#sa-main" class="sa-skip">{{ t('a11y.skip_to_content') }}</a>

    <AppHeader @open-settings="panelOpen = true" />

    <main id="sa-main" class="mx-auto w-full max-w-screen-sm flex-1 px-4 safe-top safe-bottom lg:max-w-2xl">
      <RouterView v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>

    <AppFooter />

    <!-- Floating, thumb-reachable accessibility trigger (always available). -->
    <button
      type="button"
      class="sa-a11y-fab sa-card safe-bottom"
      :aria-label="t('a11y.settings')"
      @click="panelOpen = true"
    >
      <SaIcon name="settings" :size="24" />
    </button>

    <AccessibilityPanel :open="panelOpen" @close="panelOpen = false" />
    <ToastHost />
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Skip link: hidden until focused (keyboard). */
.sa-skip {
  position: absolute;
  left: 0.5rem;
  top: -3rem;
  z-index: 70;
  padding: 0.6rem 1rem;
  border-radius: var(--radius-btn);
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-weight: 700;
  transition: top 0.15s ease;
}
.sa-skip:focus {
  top: 0.5rem;
}

/* Floating accessibility button — bottom-right, clear of safe-area + toasts. */
.sa-a11y-fab {
  position: fixed;
  right: 0.9rem;
  bottom: calc(0.9rem + env(safe-area-inset-bottom));
  z-index: 45;
  display: grid;
  place-items: center;
  width: 3.25rem;
  height: 3.25rem;
  border-radius: var(--radius-pill);
  color: var(--color-primary);
  box-shadow: var(--shadow-pop);
  cursor: pointer;
  transition: transform 0.12s ease;
}
@media (hover: hover) {
  .sa-a11y-fab:hover {
    transform: translateY(-2px) rotate(15deg);
  }
}
/* On larger screens the header already exposes settings; tuck the FAB away. */
@media (min-width: 640px) {
  .sa-a11y-fab {
    display: none;
  }
}
:root[data-reduced-motion='true'] .sa-skip,
:root[data-reduced-motion='true'] .sa-a11y-fab {
  transition: none;
}
:root[data-reduced-motion='true'] .sa-a11y-fab:hover {
  transform: none;
}
</style>

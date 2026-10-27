<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterView } from 'vue-router'

import ToastHost from '@/components/common/ToastHost.vue'
import { toast } from '@/components/common/useToasts'
import AccessibilityPanel from '@/components/layout/AccessibilityPanel.vue'
import AppFooter from '@/components/layout/AppFooter.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'

const { t } = useI18n()
const session = useSessionStore()
const ui = useUiStore()

// When a brand-new anonymous profile is created, nudge the learner to save their continuation code
// (they typically navigate straight into a lesson, so a sticky-ish toast catches the moment).
watch(
  () => session.lastResumeCodeForDisplay,
  (code) => {
    if (code) toast.info(t('resume.created_toast', { code }), { timeout: 12000, icon: 'sparkle' })
  },
)

/**
 * We do NOT create a profile here (that stays lazy, at the first prompt — SPEC flow). But a returning
 * learner's existing profile is loaded right away, so their class, language and progress show on the
 * first screen instead of only after they submit something. Errors are swallowed (offline / stale
 * code); ensureProfile recovers at the first prompt.
 */
onMounted(() => {
  if (session.resumeCode) void session.loadExisting()
})
</script>

<template>
  <!-- overflow-x-clip is a safety net: nothing may make the page wider than the phone. When anything
       did, mobile browsers widened the whole layout and taps landed away from the buttons they were
       aimed at. clip (unlike hidden) makes no scroll box, so the sticky header keeps working; and it
       sits here, not on <body>, whose overflow the browser hands to the window instead. -->
  <div class="flex min-h-dvh flex-col overflow-x-clip">
    <a href="#sa-main" class="sa-skip">{{ t('a11y.skip_to_content') }}</a>

    <AppHeader @open-settings="ui.settingsOpen = true" />

    <!-- Fixed padding, not safe-area: the sticky header above already clears the top inset, and
         padding that follows the (changing) insets moved every element on the page at once. -->
    <main id="sa-main" class="mx-auto w-full max-w-screen-sm flex-1 px-4 pb-3 pt-2 lg:max-w-2xl">
      <!-- Keyed by the path: opening another lesson/quiz (same route, new :sessionId) builds a fresh
           view instead of reusing the previous one with its state. (Path, not fullPath: no screen
           changes only its query/hash, and /resume drops its ?code= in place.) -->
      <RouterView v-slot="{ Component, route: viewRoute }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" :key="viewRoute.path" />
        </Transition>
      </RouterView>
    </main>

    <AppFooter />

    <!-- Settings open from the sticky header on every screen size. (A floating button used to sit
         bottom-right on phones too, but it covered answer options and the main button under it.) -->
    <AccessibilityPanel :open="ui.settingsOpen" @close="ui.settingsOpen = false" />
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
:root[data-reduced-motion='true'] .sa-skip {
  transition: none;
}
</style>

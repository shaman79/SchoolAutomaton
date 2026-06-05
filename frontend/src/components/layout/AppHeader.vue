<script setup lang="ts">
/**
 * Sticky, compact app header: logo (home link) + a compact gamification bar.
 *
 * The gamification bar pulls in F4's XpBar / StreakFlame / LevelBadge by path.
 * Those components are written by a concurrent agent and may be ABSENT when this
 * builds, so each is loaded via defineAsyncComponent with a graceful fallback
 * (a simple token-driven chip rendered from the session.gamification snapshot).
 * The whole bar only renders for authenticated learners (resume code present).
 */
import { defineAsyncComponent } from 'vue'
import { useI18n } from 'vue-i18n'

import AppLogo from '@/components/common/AppLogo.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import { useSessionStore } from '@/stores/session'

import LevelBadgeFallback from './fallbacks/LevelBadgeFallback.vue'
import StreakFlameFallback from './fallbacks/StreakFlameFallback.vue'
import XpBarFallback from './fallbacks/XpBarFallback.vue'

const { t } = useI18n()
const session = useSessionStore()

const emit = defineEmits<{ (e: 'open-settings'): void }>()

/**
 * Resolve an F4 gamification component by name, but never let a missing module
 * break the shell. The path is built dynamically (with @vite-ignore) so:
 *   - TypeScript does not statically require the file to exist (no TS2307), and
 *   - if the module is absent at runtime the loader rejects and we render the
 *     local token-driven fallback chip instead.
 * When F4 lands, the real component is picked up transparently.
 */
function gamComponent(name: string, fallback: object) {
  return defineAsyncComponent({
    loader: async () => {
      try {
        const mod = (await import(/* @vite-ignore */ `../gamification/${name}.vue`)) as {
          default: object
        }
        return mod.default ?? fallback
      } catch {
        return fallback
      }
    },
    errorComponent: fallback as ReturnType<typeof defineAsyncComponent>,
    loadingComponent: fallback as ReturnType<typeof defineAsyncComponent>,
    delay: 0,
    timeout: 4000,
  })
}

const XpBar = gamComponent('XpBar', XpBarFallback)
const StreakFlame = gamComponent('StreakFlame', StreakFlameFallback)
const LevelBadge = gamComponent('LevelBadge', LevelBadgeFallback)
</script>

<template>
  <header
    class="sticky top-0 z-40 border-b border-[var(--color-line)] backdrop-blur safe-top"
    style="background: color-mix(in srgb, var(--color-surface) 86%, transparent)"
  >
    <div
      class="mx-auto flex w-full max-w-screen-sm items-center gap-3 px-4 py-2 lg:max-w-2xl"
    >
      <RouterLink
        to="/"
        class="sa-logo flex items-center gap-2 font-extrabold tracking-tight"
        :aria-label="t('app.name')"
      >
        <AppLogo :size="36" />
        <span class="hidden text-lg sm:inline">{{ t('app.name') }}</span>
      </RouterLink>

      <!-- Compact gamification bar: authenticated learners only. -->
      <div
        v-if="session.isAuthenticated && session.gamification"
        class="ml-auto flex min-w-0 items-center gap-2"
        role="group"
        :aria-label="t('gamification.bar_label')"
      >
        <component :is="LevelBadge" :snapshot="session.gamification" :level="session.level" />
        <component :is="StreakFlame" :streak="session.gamification.streak" />
        <component
          :is="XpBar"
          class="hidden w-28 sm:block lg:w-40"
          :snapshot="session.gamification"
        />
      </div>

      <!-- Settings trigger lives in the header on >=sm; on phones the floating FAB (App.vue) is primary. -->
      <button
        type="button"
        class="sa-tap grid place-items-center rounded-[var(--radius-pill)] text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-2)]"
        :class="session.isAuthenticated && session.gamification ? 'ml-2' : 'ml-auto'"
        :aria-label="t('a11y.settings')"
        @click="emit('open-settings')"
      >
        <SaIcon name="settings" :size="22" />
      </button>
    </div>
  </header>
</template>

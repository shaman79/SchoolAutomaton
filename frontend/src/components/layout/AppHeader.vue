<script setup lang="ts">
/**
 * Sticky, compact app header: logo (home link) + a compact gamification bar.
 * The gamification bar (level / streak / XP) renders only for authenticated learners.
 */
import { useI18n } from 'vue-i18n'

import AppLogo from '@/components/common/AppLogo.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import LevelBadge from '@/components/gamification/LevelBadge.vue'
import StreakFlame from '@/components/gamification/StreakFlame.vue'
import XpBar from '@/components/gamification/XpBar.vue'
import { useSessionStore } from '@/stores/session'

const { t } = useI18n()
const session = useSessionStore()

const emit = defineEmits<{ (e: 'open-settings'): void }>()
</script>

<template>
  <header
    class="sticky top-0 z-40 border-b border-[var(--color-line)] backdrop-blur safe-top"
    style="background: color-mix(in srgb, var(--color-surface) 86%, transparent)"
  >
    <div class="mx-auto flex w-full max-w-screen-sm items-center gap-3 px-4 py-2 lg:max-w-2xl">
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
        <LevelBadge :level="session.level" size="sm" />
        <StreakFlame :streak="session.gamification.streak" />
        <XpBar
          class="hidden w-28 sm:block lg:w-40"
          :snapshot="session.gamification"
          hide-badge
          size="sm"
        />
      </div>

      <!-- My lessons (history) — available once a learner has a profile/resume code. -->
      <RouterLink
        v-if="session.resumeCode"
        :to="{ name: 'history' }"
        class="sa-tap grid place-items-center rounded-[var(--radius-pill)] text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-2)]"
        :class="session.isAuthenticated && session.gamification ? 'ml-2' : 'ml-auto'"
        :aria-label="t('history.title')"
      >
        <SaIcon name="books" :size="22" :title="t('history.title')" />
      </RouterLink>

      <!-- Settings trigger lives in the header on >=sm; on phones the floating FAB (App.vue) is primary. -->
      <button
        type="button"
        class="sa-tap grid place-items-center rounded-[var(--radius-pill)] text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-2)]"
        :class="session.resumeCode ? 'ml-1' : (session.isAuthenticated && session.gamification ? 'ml-2' : 'ml-auto')"
        :aria-label="t('a11y.settings')"
        @click="emit('open-settings')"
      >
        <SaIcon name="settings" :size="22" />
      </button>
    </div>
  </header>
</template>

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

      <!-- Compact gamification bar → full progress. Gated on the snapshot being loaded (which on app
           boot is hydrated from the cached resume code), NOT on a fully-loaded profile — otherwise a
           returning learner sees the data nowhere to tap until they submit a prompt. -->
      <RouterLink
        v-if="session.gamification"
        :to="{ name: 'stats' }"
        class="ml-auto flex min-w-0 items-center gap-1.5 rounded-[var(--radius-pill)] px-1.5 py-1 hover:bg-[var(--color-surface-2)] sm:gap-2.5"
        :aria-label="t('stats.title')"
      >
        <LevelBadge :level="session.level" size="sm" />
        <!-- Icon + count only here (the textual "N-day streak" label is the width hog on phones and
             just repeats the count); the full label lives on the /stats screen. -->
        <StreakFlame :streak="session.gamification.streak" size="sm" :show-label="false" />
        <XpBar
          class="hidden w-24 sm:block lg:w-40"
          :snapshot="session.gamification"
          hide-badge
          size="sm"
        />
      </RouterLink>

      <!-- Trailing icon group: history + settings. One right-push (ml-auto only when the gamification
           pill isn't there to do it) and one uniform gap, so spacing no longer depends on which
           optional items are present. -->
      <div class="flex items-center gap-1" :class="{ 'ml-auto': !session.gamification }">
        <!-- My lessons (history) — available once a learner has a profile/resume code. -->
        <RouterLink
          v-if="session.resumeCode"
          :to="{ name: 'history' }"
          class="sa-tap grid place-items-center rounded-[var(--radius-pill)] text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-2)]"
          :aria-label="t('history.title')"
        >
          <SaIcon name="books" :size="22" :title="t('history.title')" />
        </RouterLink>

        <!-- Settings trigger lives in the header on >=sm; on phones the floating FAB (App.vue) is primary. -->
        <button
          type="button"
          class="sa-tap grid place-items-center rounded-[var(--radius-pill)] text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-2)]"
          :aria-label="t('a11y.settings')"
          @click="emit('open-settings')"
        >
          <SaIcon name="settings" :size="22" />
        </button>
      </div>
    </div>
  </header>
</template>

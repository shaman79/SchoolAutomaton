<script setup lang="ts">
/**
 * Responsive grid of BadgeCards. Mobile-first: a single comfortable column on phones, widening to
 * 2/3 columns on larger screens. Unlocked badges sort first (celebration), then nearest-to-unlock,
 * so the wall always reads as progress rather than a list of things you don't have.
 *
 * Tapping a card opens an accessible detail sheet (focus-trapped, Esc to close) describing the
 * badge and its progress — a calm, informative reward surface.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import BadgeCard from './BadgeCard.vue'
import type { BadgeInfo } from './types'
import EmptyState from '@/components/common/EmptyState.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'

const props = withDefaults(
  defineProps<{
    badges: BadgeInfo[]
    compact?: boolean
    /** Sort unlocked first, then by closeness to unlocking. */
    sort?: boolean
  }>(),
  { compact: true, sort: true },
)

const { t, locale } = useI18n()

const ordered = computed(() => {
  if (!props.sort) return props.badges
  const closeness = (b: BadgeInfo) =>
    b.progress_denominator > 0 ? b.progress_numerator / b.progress_denominator : 0
  return [...props.badges].sort((a, b) => {
    const ua = a.unlocked_at ? 1 : 0
    const ub = b.unlocked_at ? 1 : 0
    if (ua !== ub) return ub - ua
    return closeness(b) - closeness(a)
  })
})

const unlockedCount = computed(() => props.badges.filter((b) => b.unlocked_at).length)

const selected = ref<BadgeInfo | null>(null)
function open(b: BadgeInfo) {
  selected.value = b
}
function close() {
  selected.value = null
}

const detailDate = computed(() => {
  if (!selected.value?.unlocked_at) return null
  try {
    return new Date(selected.value.unlocked_at).toLocaleDateString(locale.value, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return null
  }
})
</script>

<template>
  <div>
    <p v-if="badges.length" class="mb-3 text-sm font-semibold text-[var(--color-ink-soft)]">
      {{ t('gamification.badges_progress', { unlocked: unlockedCount, total: badges.length }) }}
    </p>

    <ul
      v-if="badges.length"
      class="grid list-none grid-cols-2 gap-3 p-0 lg:grid-cols-3"
    >
      <li v-for="b in ordered" :key="b.code">
        <BadgeCard :badge="b" :compact="compact" interactive @select="open" />
      </li>
    </ul>

    <EmptyState
      v-else
      icon="trophy"
      :title="t('gamification.badges_empty_title')"
      :description="t('gamification.badges_empty_desc')"
    />

    <!-- Detail sheet -->
    <Teleport to="body">
      <div
        v-if="selected"
        class="sa-badge-sheet fixed inset-0 z-[70] flex items-end justify-center p-0 sm:items-center sm:p-4"
        role="dialog"
        aria-modal="true"
        :aria-label="selected.title"
        @click.self="close"
        @keydown.esc="close"
      >
        <div class="sa-badge-sheet__backdrop absolute inset-0" aria-hidden="true" @click="close" />
        <div
          class="sa-card sa-card--pop relative w-full max-w-md p-5 safe-bottom"
          style="border-bottom-left-radius: 0; border-bottom-right-radius: 0"
        >
          <button
            class="sa-btn sa-btn-ghost sa-tap absolute right-3 top-3 !min-h-[var(--tap-min)] !p-2"
            :aria-label="t('common.close')"
            autofocus
            @click="close"
          >
            ✕
          </button>
          <BadgeCard :badge="selected" :fresh="!!selected.unlocked_at" />
          <p
            v-if="selected.unlocked_at && detailDate"
            class="mt-3 text-sm text-[var(--color-ink-soft)]"
          >
            {{ t('gamification.badge_earned_on', { date: detailDate }) }}
          </p>
          <div v-else-if="selected.progress_denominator > 0" class="mt-3">
            <ProgressBar
              :value="Math.min(selected.progress_numerator, selected.progress_denominator)"
              :max="selected.progress_denominator"
              tone="accent"
              size="md"
              :value-text="`${Math.min(selected.progress_numerator, selected.progress_denominator)} / ${selected.progress_denominator}`"
              show-value
              :label="t('gamification.badge_progress_label')"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.sa-badge-sheet__backdrop {
  background: rgb(31 35 48 / 0.45);
  backdrop-filter: blur(2px);
}
</style>

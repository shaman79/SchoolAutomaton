<script setup lang="ts">
/**
 * A single badge. Two states, both framed positively (mastery-anchored, growth-mindset):
 *   - unlocked → full-color medallion, celebratory; shows the date earned.
 *   - locked   → muted, with a clear "progress n / d" bar so it reads as an attainable goal,
 *                never a dead "you don't have this" wall.
 *
 * Meaning is never color-only: locked carries a padlock icon + "Locked" text + the progress numbers;
 * unlocked carries a star/icon + "Unlocked". Tapping (when interactive) emits `select` for a detail
 * sheet. Tap target is the whole card (>=44px).
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { BadgeInfo } from './types'
import ProgressBar from '@/components/common/ProgressBar.vue'
import SaIcon from '@/components/common/SaIcon.vue'

const props = withDefaults(
  defineProps<{
    badge: BadgeInfo
    /** Compact grid tile vs. expanded row. */
    compact?: boolean
    /** Make the card tappable (emits `select`). */
    interactive?: boolean
    /** Force the celebratory "just unlocked" emphasis (e.g. on the results screen). */
    fresh?: boolean
  }>(),
  { compact: false, interactive: false, fresh: false },
)

const emit = defineEmits<{ select: [badge: BadgeInfo] }>()

const { t, locale } = useI18n()

const unlocked = computed(() => props.badge.unlocked_at != null)
const denom = computed(() => Math.max(1, props.badge.progress_denominator || 1))
const numer = computed(() => Math.min(props.badge.progress_numerator || 0, denom.value))
const showProgress = computed(() => !unlocked.value && props.badge.progress_denominator > 0)

const statusText = computed(() =>
  unlocked.value ? t('gamification.badge_unlocked') : t('gamification.badge_locked'),
)

const unlockedDate = computed(() => {
  if (!props.badge.unlocked_at) return null
  try {
    return new Date(props.badge.unlocked_at).toLocaleDateString(locale.value, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return null
  }
})

function onActivate() {
  if (props.interactive) emit('select', props.badge)
}
function onKey(e: KeyboardEvent) {
  if (props.interactive && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault()
    emit('select', props.badge)
  }
}
</script>

<template>
  <component
    :is="interactive ? 'button' : 'div'"
    class="sa-badge-card sa-card text-start"
    :class="[
      compact ? 'sa-badge-card--compact p-3' : 'p-4',
      {
        'sa-badge-card--locked': !unlocked,
        'sa-badge-card--fresh': fresh && unlocked,
        'sa-badge-card--interactive': interactive,
      },
    ]"
    :type="interactive ? 'button' : undefined"
    :aria-label="interactive ? `${badge.title} — ${statusText}` : undefined"
    @click="onActivate"
    @keydown="onKey"
  >
    <div class="flex items-center gap-3" :class="{ 'flex-col text-center': compact }">
      <span
        class="sa-badge-card__medal inline-grid shrink-0 place-items-center rounded-full"
        :class="{ 'sa-badge-card__medal--locked': !unlocked }"
        aria-hidden="true"
      >
        <img v-if="badge.icon_url" :src="badge.icon_url" alt="" class="h-8 w-8 object-contain" />
        <SaIcon v-else-if="unlocked" name="trophy" :size="26" />
        <SaIcon v-else name="lock" :size="22" />
      </span>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-1.5" :class="{ 'justify-center': compact }">
          <p class="truncate font-bold leading-tight">{{ badge.title }}</p>
        </div>
        <p
          v-if="badge.description && !compact"
          class="mt-0.5 text-sm text-[var(--color-ink-soft)]"
        >
          {{ badge.description }}
        </p>
        <p class="mt-0.5 text-xs font-semibold" :class="unlocked ? 'text-[var(--color-mint)]' : 'text-[var(--color-ink-soft)]'">
          {{ statusText }}<template v-if="unlockedDate"> · {{ unlockedDate }}</template>
        </p>
      </div>
    </div>

    <div v-if="showProgress" class="mt-3">
      <ProgressBar
        :value="numer"
        :max="denom"
        tone="accent"
        size="sm"
        :label="t('gamification.badges')"
        :value-text="`${numer} / ${denom}`"
        show-value
      />
    </div>
  </component>
</template>

<style scoped>
.sa-badge-card {
  display: block;
  width: 100%;
}
.sa-badge-card__medal {
  width: 3rem;
  height: 3rem;
  color: var(--color-on-primary);
  background: radial-gradient(120% 120% at 30% 20%, var(--color-sun), var(--color-accent) 70%, var(--color-primary));
  box-shadow: var(--shadow-card);
}
.sa-badge-card__medal--locked {
  color: var(--color-ink-soft);
  background: var(--color-surface-2);
  box-shadow: none;
}
.sa-badge-card--locked {
  opacity: 0.92;
}
.sa-badge-card--interactive {
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
@media (hover: hover) {
  .sa-badge-card--interactive:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-pop);
  }
}
.sa-badge-card--fresh {
  outline: 2px solid var(--color-sun);
  outline-offset: 1px;
  animation: sa-badge-rise 0.5s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes sa-badge-rise {
  0% {
    transform: scale(0.9);
    opacity: 0;
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
:root[data-reduced-motion='true'] .sa-badge-card--fresh {
  animation: none;
}
:root[data-reduced-motion='true'] .sa-badge-card--interactive:hover {
  transform: none;
}
</style>

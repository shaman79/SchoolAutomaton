<script setup lang="ts">
/**
 * LoadingView — the playful "we're building it" screen. Drives generation via useGeneration
 * (which wraps the frozen generation store + SSE). Shows an animated mascot/spinner, a live
 * checklist of plan sections that tick off as `section` SSE events arrive, an accessible
 * progress bar, and rotating encouraging copy. Navigates to /lesson or /test on ready and
 * offers a friendly retry on error. All motion is reduced-motion aware.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import SaButton from '@/components/common/SaButton.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import { useGeneration } from '@/composables/useGeneration'
import { useReducedMotion } from '@/composables/useReducedMotion'

const props = defineProps<{ sessionId: string }>()
const { t } = useI18n()
const router = useRouter()
const { reduced } = useReducedMotion()

const g = useGeneration(props.sessionId)

// Rotating encouragement messages (only when motion is allowed; otherwise a single steady line).
const encouragements = [
  'loading.cheer_1',
  'loading.cheer_2',
  'loading.cheer_3',
  'loading.cheer_4',
]
const cheerIdx = ref(0)
let cheerTimer: ReturnType<typeof setInterval> | null = null

const headline = computed(() => {
  switch (g.phase.value) {
    case 'ready':
      return t('loading.almost')
    case 'planning':
      return t('loading.planning')
    case 'building':
      return g.resultMode.value === 'test' ? t('loading.building_test') : t('loading.thinking')
    case 'error':
      return t('loading.error_title')
    default:
      return t('loading.starting')
  }
})

// Navigate the moment we know where to go.
watch(
  () => g.destination.value,
  (dest) => {
    if (dest) router.replace(dest)
  },
)

onMounted(() => {
  g.begin().catch(() => {
    /* errors surface via the store status -> g.isError */
  })
  if (!reduced.value) {
    cheerTimer = setInterval(() => {
      cheerIdx.value = (cheerIdx.value + 1) % encouragements.length
    }, 3200)
  }
})

watch(
  () => g.isError.value,
  (err) => {
    if (err && cheerTimer) {
      clearInterval(cheerTimer)
      cheerTimer = null
    }
  },
)
</script>

<template>
  <section class="sa-loading">
    <!-- ERROR STATE -->
    <template v-if="g.isError.value">
      <div class="sa-loading__mascot sa-loading__mascot--sad" aria-hidden="true">😟</div>
      <h2 class="sa-loading__title" role="alert">{{ headline }}</h2>
      <p class="sa-loading__sub">{{ g.errorMessage.value || t('loading.error_body') }}</p>
      <div class="sa-loading__actions">
        <SaButton variant="primary" icon="back" @click="g.retry()">
          {{ t('common.retry') }}
        </SaButton>
        <SaButton variant="ghost" to="/">{{ t('common.back') }}</SaButton>
      </div>
    </template>

    <!-- WORKING / READY STATE -->
    <template v-else>
      <div
        class="sa-loading__mascot"
        :class="{ 'sa-loading__mascot--bob': !reduced }"
        aria-hidden="true"
      >
        {{ g.isReady.value ? '🎉' : '🧠' }}
      </div>

      <h2 class="sa-loading__title">{{ headline }}</h2>

      <!-- aria-live so screen-reader users hear the encouragement update -->
      <p class="sa-loading__sub" role="status" aria-live="polite">
        {{ t(encouragements[cheerIdx]) }}
      </p>

      <div class="sa-loading__bar">
        <ProgressBar
          :indeterminate="g.progressPct.value === null"
          :value="g.progressPct.value ?? 0"
          tone="primary"
          size="lg"
          :label="t('loading.progress_label')"
        />
      </div>

      <!-- Live checklist of plan sections (ticks off as `section` events arrive). -->
      <ul v-if="g.checklist.value.length" class="sa-loading__list" aria-label="Plan">
        <li
          v-for="s in g.checklist.value"
          :key="s.ordinal"
          class="sa-loading__item"
          :class="{ 'sa-loading__item--done': s.done }"
        >
          <span class="sa-loading__tick" aria-hidden="true">{{ s.done ? '✓' : '○' }}</span>
          <span class="sa-loading__item-label">{{ s.title || s.kind }}</span>
          <span v-if="s.done" class="sr-only">{{ t('loading.section_done') }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.sa-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 3rem 0 4rem;
  text-align: center;
}
.sa-loading__mascot {
  font-size: 3.5rem;
  line-height: 1;
}
.sa-loading__mascot--bob {
  animation: sa-bob 2.4s ease-in-out infinite;
}
.sa-loading__title {
  font-size: 1.4rem;
  font-weight: 800;
}
.sa-loading__sub {
  margin: 0;
  color: var(--color-ink-soft);
  max-width: 36ch;
}
.sa-loading__bar {
  width: 100%;
  max-width: 24rem;
}
.sa-loading__list {
  width: 100%;
  max-width: 24rem;
  list-style: none;
  margin: 0.5rem 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  text-align: start;
}
.sa-loading__item {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-btn);
  background: var(--color-surface-2);
  color: var(--color-ink-soft);
  transition: background 0.25s ease, color 0.25s ease;
}
.sa-loading__item--done {
  background: color-mix(in srgb, var(--color-mint) 14%, var(--color-surface));
  color: var(--color-ink);
  font-weight: 600;
}
.sa-loading__tick {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.4rem;
  height: 1.4rem;
  flex: none;
  border-radius: var(--radius-pill);
  font-size: 0.85rem;
}
.sa-loading__item--done .sa-loading__tick {
  background: var(--color-mint);
  color: var(--color-on-mint);
}
.sa-loading__item-label {
  text-transform: capitalize;
}
.sa-loading__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  justify-content: center;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@keyframes sa-bob {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}
:root[data-reduced-motion='true'] .sa-loading__mascot--bob,
:root[data-reduced-motion='true'] .sa-loading__item {
  animation: none;
  transition: none;
}
</style>

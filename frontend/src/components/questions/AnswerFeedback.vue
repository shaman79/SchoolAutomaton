<script setup lang="ts">
/**
 * Shared answer feedback (SPEC frontend + gamification_design FEEDBACK rules):
 *   role="status" aria-live="polite" — announced to screen readers.
 *   Meaning is NEVER color-only: an icon (check / dash) + localized text always accompany it.
 *   Growth-mindset copy: "not yet" framing on error, never a bare "wrong".
 *   Optional success chime (only when sound enabled) + a reduced-motion-aware micro-animation.
 * Drives off the server GradeResult-shaped fields; correctness/explanation come from the
 * grading endpoint (answers are server-only until then).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import SafeContent from '@/components/content/SafeContent.vue'
import { useReducedMotion } from '@/composables/useReducedMotion'
import type { FeedbackBlock } from '@/types/session'

const props = withDefaults(
  defineProps<{
    /** True correct, false incorrect, null/undefined => partially correct (use partial). */
    correct: boolean
    /** 0..1 partial credit; >0 and <1 shows a "partly there" state. */
    partial?: number
    /** Localized growth-mindset feedback text (server-provided). Falls back to i18n. */
    feedback?: FeedbackBlock | null
    /** Localized model explanation (untrusted markdown — rendered via SafeContent). */
    explanation?: string | null
    /** Misconception correction, if the grader returned one. */
    misconception?: { description: string; refutation: string } | null
    /** Play a chime on correct (gated on profile sound pref by the caller). */
    sound?: boolean
  }>(),
  { partial: 1, feedback: null, explanation: null, misconception: null, sound: false },
)

const { t } = useI18n()
const { reduced } = useReducedMotion()

type State = 'correct' | 'partial' | 'incorrect'
const state = computed<State>(() => {
  if (props.correct) return 'correct'
  if (props.partial > 0 && props.partial < 1) return 'partial'
  return 'incorrect'
})

// Icon is a non-color cue (WCAG: never color alone). Text is the primary cue.
const icon = computed(() => {
  switch (state.value) {
    case 'correct':
      return '✓'
    case 'partial':
      return '≈'
    default:
      return '↻'
  }
})

// A short, fixed status label. Kept terse on purpose: the verbose server feedback.text used to be
// shown here as a big headline and read as repetitive ("Skvělá práce!" on every answer). The
// valuable content is the explanation / misconception below — so when those are present we keep the
// status as a screen-reader-only announcement (the icon shape still carries the non-color cue), and
// only surface a visible label when there is nothing else to show.
const statusLabel = computed(() => {
  switch (state.value) {
    case 'correct':
      return t('common.correct')
    case 'partial':
      return t('feedback.partial')
    default:
      return t('common.not_yet')
  }
})

const hasBody = computed(() => Boolean(props.explanation || props.misconception))

// brief enter animation — gated on reduced motion
const animate = ref(false)
function trigger() {
  if (reduced.value) {
    animate.value = false
    return
  }
  animate.value = false
  // next frame so the class toggles and re-runs
  requestAnimationFrame(() => (animate.value = true))
  if (props.sound && state.value === 'correct') playChime()
}

let audioCtx: AudioContext | null = null
function playChime() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctx) return
    audioCtx = audioCtx ?? new Ctx()
    const o = audioCtx.createOscillator()
    const g = audioCtx.createGain()
    o.type = 'sine'
    o.frequency.value = 880
    g.gain.value = 0.0001
    o.connect(g)
    g.connect(audioCtx.destination)
    const now = audioCtx.currentTime
    g.gain.exponentialRampToValueAtTime(0.12, now + 0.02)
    g.gain.exponentialRampToValueAtTime(0.0001, now + 0.28)
    o.frequency.setValueAtTime(880, now)
    o.frequency.setValueAtTime(1175, now + 0.1)
    o.start(now)
    o.stop(now + 0.3)
  } catch {
    /* audio not available — silent */
  }
}

onMounted(trigger)
watch(state, trigger)
</script>

<template>
  <div
    class="sa-feedback"
    :class="[`sa-feedback--${state}`, { 'sa-feedback--pop': animate }]"
    role="status"
    aria-live="polite"
  >
    <div class="sa-feedback__head">
      <span class="sa-feedback__icon" aria-hidden="true">{{ icon }}</span>
      <span class="sa-feedback__headline" :class="{ 'sr-only': hasBody }">{{ statusLabel }}</span>
    </div>

    <SafeContent
      v-if="explanation"
      :markdown="explanation"
      class="sa-feedback__explanation"
    />

    <div v-if="misconception" class="sa-feedback__misconception">
      <SafeContent :markdown="misconception.refutation" />
    </div>
  </div>
</template>

<style scoped>
.sa-feedback {
  border-radius: var(--radius-card);
  padding: 0.85rem 1rem;
  border: 2px solid var(--color-line);
  background: var(--color-surface);
}
.sa-feedback__head {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-weight: 700;
}
.sa-feedback__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  border-radius: var(--radius-pill);
  font-size: 1.1rem;
  flex: none;
  color: var(--color-on-primary);
}
/* Color reinforces the icon+text — it is never the only signal. */
.sa-feedback--correct {
  border-color: var(--color-mint);
  background: color-mix(in srgb, var(--color-mint) 12%, var(--color-surface));
}
.sa-feedback--correct .sa-feedback__icon {
  background: var(--color-mint);
  color: var(--color-on-mint);
}
.sa-feedback--partial {
  border-color: var(--color-sun);
  background: color-mix(in srgb, var(--color-sun) 14%, var(--color-surface));
}
.sa-feedback--partial .sa-feedback__icon {
  background: var(--color-sun);
  color: var(--color-ink);
}
.sa-feedback--incorrect {
  border-color: var(--color-coral);
  background: color-mix(in srgb, var(--color-coral) 10%, var(--color-surface));
}
.sa-feedback--incorrect .sa-feedback__icon {
  background: var(--color-coral);
  color: var(--color-on-coral);
}
.sa-feedback__explanation,
.sa-feedback__misconception {
  margin-top: 0.6rem;
  font-weight: 400;
}
.sa-feedback__misconception {
  border-top: 1px dashed var(--color-line);
  padding-top: 0.6rem;
}
/* Micro-animation only when motion is allowed (class is gated in script). */
.sa-feedback--pop {
  animation: sa-feedback-pop 0.28s ease-out;
}
@keyframes sa-feedback-pop {
  0% {
    transform: scale(0.96);
    opacity: 0.4;
  }
  60% {
    transform: scale(1.015);
  }
  100% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>

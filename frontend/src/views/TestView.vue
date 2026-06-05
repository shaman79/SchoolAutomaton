<script setup lang="ts">
/**
 * TestView — the TestRunner. Resolves the quiz id (generation store, else request status), loads
 * the quiz and starts an attempt (test store). Presents ONE question at a time via QuestionRenderer
 * with a progress bar; on answer it grades through the store, shows immediate feedback inline (the
 * renderer renders AnswerFeedback off the GradeResult), and pops a combo/XP toast + celebration.
 * "Next" advances; after the final question it calls test.complete() and routes to /results.
 * Mobile-first, touch-first, reduced-motion aware, WCAG 2.2 AA.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import SaButton from '@/components/common/SaButton.vue'
import { toast } from '@/components/common/useToasts'
import QuestionRenderer from '@/components/questions/QuestionRenderer.vue'
import { useCelebration } from '@/composables/useCelebration'
import { api } from '@/lib/api'
import { useGenerationStore } from '@/stores/generation'
import { usePrefsStore } from '@/stores/prefs'
import { useTestStore } from '@/stores/test'
import type { AnswerEvent } from '@/types/question'

const props = defineProps<{ sessionId: string }>()
const { t } = useI18n()
const router = useRouter()
const gen = useGenerationStore()
const prefs = usePrefsStore()
const test = useTestStore()
const { celebrateCorrect } = useCelebration()

const failed = ref(false)
const submitting = ref(false)
const finishing = ref(false)

const current = computed(() => test.current)
const total = computed(() => test.total)
const indexHuman = computed(() => test.currentIndex + 1)

// Feedback for the question currently on screen (results keyed by questionId).
const currentFeedback = computed(() => {
  const id = current.value?.item.id
  return id != null ? (test.results[id] ?? null) : null
})

const answeredCurrent = computed(() => currentFeedback.value != null)
const isLast = computed(() => test.currentIndex >= total.value - 1)

async function onAnswer(e: AnswerEvent) {
  if (submitting.value || answeredCurrent.value) return
  submitting.value = true
  try {
    const res = await test.submit(e)

    // Combo / XP feedback as a toast (in addition to the inline AnswerFeedback).
    if (res.is_correct) {
      void celebrateCorrect(null)
      const combo = res.combo_multiplier > 1 ? ` ·  ×${res.combo_multiplier.toFixed(1)}` : ''
      toast.success(`+${res.xp_awarded} ${t('gamification.xp')}${combo}`, { icon: 'star' })
    }
    if (res.level_up) {
      toast.success(t('test.level_up', { level: res.level_up.to_level }), { icon: 'trophy' })
    }
    for (const b of res.new_badges) {
      toast.success(t('test.badge_unlocked', { title: b.title }), { icon: 'trophy', timeout: 6000 })
    }
  } catch {
    toast.error(t('test.grade_error'))
  } finally {
    submitting.value = false
  }
}

async function advance() {
  if (isLast.value) {
    finishing.value = true
    try {
      await test.complete()
    } catch {
      /* still route to results; the results view tolerates a missing summary */
    } finally {
      finishing.value = false
    }
    router.replace({ name: 'results', params: { sessionId: props.sessionId } })
    return
  }
  test.next()
}

async function onNext() {
  if (!answeredCurrent.value) return
  await advance()
}

// Escape hatch: a learner can always move on, even if a question can't be answered — they're never
// stranded (the backend also drops unanswerable items, so this is a rare safety net).
function onSkip() {
  if (submitting.value || finishing.value) return
  void advance()
}

onMounted(async () => {
  try {
    let id = gen.quizId
    if (!id) {
      const status = await api.getRequestStatus(props.sessionId)
      id = status.quiz_id
    }
    if (id) await test.load(id)
    else failed.value = true
  } catch {
    failed.value = true
  }
})
</script>

<template>
  <section v-if="test.quiz" class="sa-test">
    <!-- Sticky-ish progress header -->
    <header class="sa-test__header">
      <div class="sa-test__meta">
        <h1 class="sa-test__title">{{ test.quiz.title }}</h1>
        <span class="sa-test__count" aria-hidden="true">
          {{ indexHuman }} / {{ total }}
        </span>
      </div>
      <ProgressBar
        :value="indexHuman"
        :max="total"
        tone="primary"
        size="md"
        :label="t('test.progress_label')"
        :value-text="t('test.progress_value', { current: indexHuman, total })"
      />
    </header>

    <!-- One question at a time -->
    <div v-if="current" :key="current.item.id" class="sa-card sa-test__question">
      <p class="sa-test__points">
        {{ t('test.points', { n: current.points }) }}
      </p>
      <QuestionRenderer
        :item="current.item"
        :feedback="currentFeedback"
        :disabled="answeredCurrent || submitting"
        :sound="prefs.sound"
        @answer="onAnswer"
      />
    </div>

    <!-- One action at a time: Check lives in the question; once graded it's replaced by Next/Finish.
         Before answering, only a subtle Skip is offered so the learner is never stuck. -->
    <div class="sa-test__footer safe-bottom">
      <SaButton
        v-if="answeredCurrent"
        variant="primary"
        size="lg"
        block
        :icon="isLast ? 'trophy' : 'sparkle'"
        :icon-right="!isLast"
        :loading="finishing"
        @click="onNext"
      >
        {{ isLast ? t('test.finish') : t('common.next') }}
      </SaButton>
      <button v-else type="button" class="sa-test__skip" @click="onSkip">
        {{ isLast ? t('test.skip_finish') : t('test.skip') }}
      </button>
    </div>
  </section>

  <EmptyState
    v-else-if="failed"
    icon="hint"
    :title="t('test.load_error_title')"
    :description="t('test.load_error_body')"
    announce
  >
    <SaButton variant="primary" to="/" icon="home">{{ t('common.back') }}</SaButton>
  </EmptyState>

  <div v-else class="sa-test__loading">
    <LoadingSpinner :size="40" :label="t('common.loading')" />
  </div>
</template>

<style scoped>
.sa-test {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem 0 1rem;
  min-height: 70vh;
}
.sa-test__header {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-test__meta {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.sa-test__title {
  font-size: 1.2rem;
  font-weight: 800;
  line-height: 1.2;
  min-width: 0;
}
.sa-test__count {
  flex: none;
  font-weight: 700;
  color: var(--color-ink-soft);
  font-variant-numeric: tabular-nums;
}
.sa-test__question {
  padding: 1.1rem;
}
.sa-test__points {
  margin: 0 0 0.6rem;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-primary);
}
.sa-test__footer {
  margin-top: auto;
  padding-top: 0.5rem;
}
.sa-test__skip {
  display: block;
  margin: 0 auto;
  min-height: var(--tap-min);
  padding: 0.5rem 1rem;
  color: var(--color-ink-soft);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.sa-test__loading {
  display: grid;
  place-items: center;
  padding: 4rem 0;
}
</style>

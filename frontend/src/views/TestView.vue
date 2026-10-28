<script setup lang="ts">
/**
 * TestView — the TestRunner. Resolves the quiz id (generation store, else request status), loads
 * the quiz and starts an attempt (test store). Presents ONE question at a time via QuestionRenderer
 * with a progress bar; on answer it grades through the store, shows immediate feedback inline (the
 * renderer renders AnswerFeedback off the GradeResult), and pops a combo/XP toast + celebration.
 * "Next" advances; after the final question it calls test.complete() and routes to /results.
 * RESUME: the store reloads the attempt from the server, so a refresh / break / other device lands on
 * the same question with earlier answers (and their feedback) back in place.
 * The ROUTE decides which quiz opens; a quiz left in the store from earlier is never shown here.
 * A failed answer keeps the question answerable (friendly toast); a support result (crisis net)
 * shows the help block instead of feedback, ungraded and still answerable.
 * Mobile-first, touch-first, reduced-motion aware, WCAG 2.2 AA.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import CrisisCard from '@/components/CrisisCard.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import SaButton from '@/components/common/SaButton.vue'
import { toast } from '@/components/common/useToasts'
import { announceBadges } from '@/components/gamification/announceBadges'
import ReadAloudButton from '@/components/content/ReadAloudButton.vue'
import CorrectAnswer from '@/components/questions/CorrectAnswer.vue'
import { speechLang } from '@/lib/speechLang'
import QuestionRenderer from '@/components/questions/QuestionRenderer.vue'
import { useCelebration } from '@/composables/useCelebration'
import { api } from '@/lib/api'
import { answerErrorKey } from '@/lib/errors'
import { useGenerationStore } from '@/stores/generation'
import { usePrefsStore } from '@/stores/prefs'
import { useTestStore } from '@/stores/test'
import type { AnswerEvent } from '@/types/question'
import type { AnswerSupport } from '@/types/session'

const props = defineProps<{ sessionId: string }>()
const { t } = useI18n()
const router = useRouter()
const gen = useGenerationStore()
const prefs = usePrefsStore()
const test = useTestStore()
const { celebrateCorrect } = useCelebration()

const failed = ref(false)
let leaving = false
onBeforeUnmount(() => {
  leaving = true
})
// Only THIS route's quiz (the store — persisted per tab — may still hold a previous one).
const quiz = computed(() => (test.quiz?.request_id === props.sessionId ? test.quiz : null))
// Support blocks (crisis net) per item id: shown in place of feedback, the question stays open.
const supportByItem = reactive<Record<number, AnswerSupport>>({})
const questionEl = ref<HTMLElement | null>(null)
const readLang = computed(() => speechLang(quiz.value?.language, prefs.educationLocale))
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

// Single morphing CTA: the footer button is "Check" (drives the question's submit) until graded,
// then becomes "Next"/"Finish". The question component hides its own Check in managed mode.
const qr = ref<{ submit?: () => void; canSubmit?: boolean } | null>(null)
const checkReady = computed(() => Boolean(qr.value?.canSubmit))
function onCheck() {
  if (submitting.value || !checkReady.value) return
  qr.value?.submit?.()
}

async function onAnswer(e: AnswerEvent) {
  if (submitting.value || answeredCurrent.value) return
  submitting.value = true
  try {
    const res = await test.submit(e)
    if (!res) {
      // Already settled on the server (answered or finished in another tab/device) — the store has
      // re-synced, so the screen now shows the up-to-date state.
      toast.info(t('test.synced'))
      return
    }
    if (res.support) {
      // Not graded or counted: the help block replaces feedback; no verdict, no sound.
      supportByItem[e.questionId] = res.support
      return
    }

    // Combo / XP feedback as a toast (in addition to the inline AnswerFeedback).
    if (res.is_correct) {
      void celebrateCorrect(null)
      const combo = res.combo_multiplier > 1 ? ` ·  ×${res.combo_multiplier.toFixed(1)}` : ''
      // A "+0 XP" toast reads as a penalty (XP shrinks as mastery grows) — only show real gains.
      if (res.xp_awarded > 0) {
        toast.success(`+${res.xp_awarded} ${t('gamification.xp')}${combo}`, { icon: 'star' })
      }
    }
    if (res.level_up) {
      toast.success(t('test.level_up', { level: res.level_up.to_level }), { icon: 'trophy' })
    }
    announceBadges(res.new_badges)
  } catch (err) {
    // The question stays answerable with the learner's input in place.
    if (!leaving) toast.error(t(answerErrorKey(err)))
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

/** The quiz id for THIS route: the generation store's only when generated for this very request. */
async function resolveQuizId(): Promise<number | null> {
  if (gen.requestId === props.sessionId && gen.quizId) return gen.quizId
  return (await api.getRequestStatus(props.sessionId)).quiz_id
}

async function openQuiz() {
  failed.value = false
  try {
    const id = await resolveQuizId()
    if (leaving) return
    if (!id) {
      failed.value = true
      return
    }
    await test.load(id)
    if (!leaving && test.resumed) {
      toast.info(t('test.resumed', { current: test.currentIndex + 1, total: test.total }))
    }
  } catch {
    if (!leaving) failed.value = true
  }
}

onMounted(openQuiz)
</script>

<template>
  <section v-if="quiz" class="sa-test">
    <!-- Sticky-ish progress header -->
    <header class="sa-test__header">
      <div class="sa-test__meta">
        <h1 class="sa-test__title">{{ quiz.title }}</h1>
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

    <!-- One question at a time (the QuestionRenderer's own root is the card; this wrapper only holds
         the points label above it — no nested card). -->
    <div v-if="current" :key="current.item.id" class="sa-test__question">
      <div class="sa-test__qhead">
        <p class="sa-test__points">
          {{ t('test.points', { n: current.points }) }}
        </p>
        <ReadAloudButton :target="questionEl" :lang="readLang" />
      </div>
      <div ref="questionEl">
      <QuestionRenderer
        ref="qr"
        :item="current.item"
        :feedback="currentFeedback"
        :disabled="answeredCurrent || submitting"
        :submitted="test.submitted[current.item.id]"
        :sound="prefs.sound"
        managed
        @answer="onAnswer"
      />
      </div>
      <CrisisCard
        v-if="supportByItem[current.item.id]"
        :message="supportByItem[current.item.id].message"
        :disclosure="supportByItem[current.item.id].disclosure"
        :resources="supportByItem[current.item.id].resources"
      />
      <CorrectAnswer :item="current.item" :feedback="currentFeedback" />
    </div>

    <!-- Single morphing CTA: Check (until graded) → Next/Finish. A subtle Skip is offered while
         unanswered so the learner is never stuck. -->
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
      <SaButton
        v-else
        variant="primary"
        size="lg"
        block
        icon="check"
        :disabled="!checkReady"
        :loading="submitting"
        @click="onCheck"
      >
        {{ t('common.check') }}
      </SaButton>
      <SaButton v-if="!answeredCurrent" variant="subtle" size="sm" @click="onSkip">
        {{ isLast ? t('test.skip_finish') : t('test.skip') }}
      </SaButton>
    </div>
  </section>

  <EmptyState
    v-else-if="failed"
    icon="hint"
    :title="t('test.load_error_title')"
    :description="t('test.load_error_body')"
    announce
  >
    <SaButton variant="primary" icon="sparkle" @click="openQuiz">{{ t('common.retry') }}</SaButton>
    <SaButton variant="ghost" to="/" icon="home">{{ t('common.back') }}</SaButton>
  </EmptyState>

  <div v-else class="sa-test__loading">
    <LoadingSpinner :size="40" :label="t('common.loading')" />
  </div>
</template>

<style scoped>
.sa-test__qhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
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
.sa-test__points {
  margin: 0 0 0.5rem;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-primary);
}
.sa-test__footer {
  margin-top: auto;
  padding-top: 0.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}
.sa-test__loading {
  display: grid;
  place-items: center;
  padding: 4rem 0;
}
</style>

<script setup lang="ts">
/**
 * DailyReviewView — "Zalij svou zahrádku" / "Water your garden": the spaced-repetition session.
 *
 * FSRS schedules every answered item for a comeback; this is where the due ones actually return
 * (GET /review/due), one question at a time. Each answer goes through POST /review/{item_id}, which
 * grades it and advances its FSRS card, mastery and XP like any other answer. Kept short on purpose
 * (SESSION_SIZE) so it fits a young learner's daily routine. It reuses the knowledge-garden metaphor:
 * a due concept is a plant that needs watering, never a failure.
 * Mirrors the quiz runner's single morphing Check → Next CTA. Mobile-first, reduced-motion aware.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import SaButton from '@/components/common/SaButton.vue'
import { toast } from '@/components/common/useToasts'
import CorrectAnswer from '@/components/questions/CorrectAnswer.vue'
import QuestionRenderer from '@/components/questions/QuestionRenderer.vue'
import { useCelebration } from '@/composables/useCelebration'
import { ApiError, api } from '@/lib/api'
import { usePrefsStore } from '@/stores/prefs'
import { useSessionStore } from '@/stores/session'
import type { AnswerEvent, ItemPublic } from '@/types/question'
import type { GradeResult } from '@/types/session'

/** A short daily round — a few minutes, not an exam. */
const SESSION_SIZE = 10

const { t } = useI18n()
const prefs = usePrefsStore()
const session = useSessionStore()
const { celebrateCorrect, celebrateLevelUp } = useCelebration()

const items = ref<ItemPublic[]>([])
const index = ref(0)
const results = ref<Record<number, GradeResult>>({})
const loading = ref(true)
const failed = ref(false)
const submitting = ref(false)
const done = ref(false)
const doneRef = ref<HTMLElement | null>(null)

// A stored code the server no longer knows (401) is treated like having no profile yet.
const staleCode = ref(false)
const hasProfile = computed(() => !!session.resumeCode && !staleCode.value)
const current = computed(() => items.value[index.value] ?? null)
const total = computed(() => items.value.length)
const feedback = computed(() => (current.value ? (results.value[current.value.id] ?? null) : null))
const answered = computed(() => feedback.value != null)
const isLast = computed(() => index.value >= total.value - 1)
const correctCount = computed(
  () => Object.values(results.value).filter((r) => r.is_correct).length,
)
// Skipped questions stay due (they come back next round), so the summary counts answered ones only.
const answeredCount = computed(() => Object.keys(results.value).length)
const skippedCount = computed(() => total.value - answeredCount.value)

// Single morphing CTA (as in the quiz): Check drives the question's own submit until it's graded.
const qr = ref<{ submit?: () => void; canSubmit?: boolean } | null>(null)
const checkReady = computed(() => Boolean(qr.value?.canSubmit))

async function load() {
  loading.value = true
  failed.value = false
  try {
    items.value = (await api.getDue(SESSION_SIZE)).items
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) staleCode.value = true
    else failed.value = true
  } finally {
    loading.value = false
  }
}

function onCheck() {
  if (submitting.value || !checkReady.value) return
  qr.value?.submit?.()
}

async function onAnswer(e: AnswerEvent) {
  if (submitting.value || answered.value) return
  submitting.value = true
  try {
    const res = await api.reviewItem(e.questionId, {
      submitted_value: e.value,
      used_hint: e.usedHint,
      latency_ms: e.latencyMs,
    })
    results.value = { ...results.value, [e.questionId]: res }
    if (res.is_correct) {
      void celebrateCorrect(null)
      if (res.xp_awarded) toast.success(`+${res.xp_awarded} ${t('gamification.xp')}`, { icon: 'star' })
    }
    if (res.level_up) {
      toast.success(t('test.level_up', { level: res.level_up.to_level }), { icon: 'trophy' })
    }
    // One toast however many badges this answer unlocked — a stack of them hid the Next button.
    const badges = res.new_badges.map((b) => b.title)
    if (badges.length) {
      const msg =
        badges.length === 1
          ? t('test.badge_unlocked', { title: badges[0] })
          : t('test.badges_unlocked', { titles: badges.join(', ') })
      toast.success(msg, { icon: 'trophy', timeout: 6000 })
    }
  } catch {
    toast.error(t('test.grade_error'))
  } finally {
    submitting.value = false
  }
}

async function advance() {
  if (!isLast.value) {
    index.value++
    return
  }
  done.value = true
  session.refreshGamification().catch(() => {
    /* the header simply keeps its last snapshot */
  })
  if (answeredCount.value && correctCount.value / answeredCount.value >= 0.8) {
    void celebrateLevelUp(doneRef.value)
  }
}

// Never strand the learner on a question they can't answer.
function onSkip() {
  if (!submitting.value) void advance()
}

onMounted(() => {
  if (hasProfile.value) void load()
  else loading.value = false
})
</script>

<template>
  <section class="sa-daily">
    <!-- No profile yet: nothing has been learned, so nothing can be due. -->
    <EmptyState
      v-if="!hasProfile"
      icon="sparkle"
      :title="t('daily.title')"
      :description="t('stats.no_profile')"
    >
      <SaButton variant="primary" to="/" icon="sparkle">{{ t('history.start_learning') }}</SaButton>
    </EmptyState>

    <div v-else-if="loading" class="sa-daily__loading">
      <LoadingSpinner :size="40" :label="t('common.loading')" />
    </div>

    <EmptyState v-else-if="failed" icon="hint" :title="t('daily.title')" :description="t('daily.load_error')" announce>
      <SaButton variant="primary" icon="back" @click="load">{{ t('common.retry') }}</SaButton>
    </EmptyState>

    <!-- Nothing due: celebrate the tidy garden instead of showing an empty screen. -->
    <EmptyState
      v-else-if="!total"
      icon="check"
      :title="t('daily.empty_title')"
      :description="t('daily.empty_body')"
      announce
    >
      <SaButton variant="primary" to="/" icon="sparkle">{{ t('lesson.learn_more') }}</SaButton>
    </EmptyState>

    <!-- Round finished. -->
    <div v-else-if="done" ref="doneRef" class="sa-card sa-daily__done" role="status" aria-live="polite">
      <span class="sa-daily__done-glyph" aria-hidden="true">🌸</span>
      <h1 class="sa-daily__title">{{ t('daily.done_title') }}</h1>
      <p class="sa-daily__intro">
        <template v-if="answeredCount">
          {{ t('daily.done_body', { correct: correctCount, total: answeredCount }) }}
        </template>
        {{ skippedCount ? t('daily.done_skipped') : t('daily.done_later') }}
      </p>
      <div class="sa-daily__actions">
        <SaButton variant="primary" size="lg" block icon="star" :to="{ name: 'stats' }">
          {{ t('results.view_progress') }}
        </SaButton>
        <SaButton variant="ghost" block icon="sparkle" to="/">{{ t('lesson.learn_more') }}</SaButton>
      </div>
    </div>

    <!-- The round: one question at a time. -->
    <template v-else-if="current">
      <header class="sa-daily__header">
        <h1 class="sa-daily__title"><span aria-hidden="true">💧</span> {{ t('daily.title') }}</h1>
        <p v-if="index === 0 && !answered" class="sa-daily__intro">{{ t('daily.intro') }}</p>
        <ProgressBar
          :value="index + 1"
          :max="total"
          tone="primary"
          size="md"
          :label="t('daily.progress_label')"
          :value-text="t('test.progress_value', { current: index + 1, total })"
        />
      </header>

      <div :key="current.id">
        <QuestionRenderer
          ref="qr"
          :item="current"
          :feedback="feedback"
          :disabled="answered || submitting"
          :sound="prefs.sound"
          managed
          @answer="onAnswer"
        />
        <CorrectAnswer :item="current" :feedback="feedback" />
      </div>

      <div class="sa-daily__footer safe-bottom">
        <SaButton
          v-if="answered"
          variant="primary"
          size="lg"
          block
          :icon="isLast ? 'check' : 'sparkle'"
          :icon-right="!isLast"
          @click="advance"
        >
          {{ isLast ? t('common.done') : t('common.next') }}
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
        <SaButton v-if="!answered" variant="subtle" size="sm" @click="onSkip">
          {{ isLast ? t('test.skip_finish') : t('test.skip') }}
        </SaButton>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sa-daily {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem 0 1rem;
  min-height: 70vh;
}
.sa-daily__header {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-daily__title {
  margin: 0;
  font-size: 1.35rem;
  font-weight: 800;
  line-height: 1.2;
}
.sa-daily__intro {
  margin: 0;
  color: var(--color-ink-soft);
}
.sa-daily__footer {
  margin-top: auto;
  padding-top: 0.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
}
.sa-daily__loading {
  display: grid;
  place-items: center;
  padding: 4rem 0;
}
.sa-daily__done {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  padding: 1.5rem 1.1rem;
  text-align: center;
}
.sa-daily__done-glyph {
  font-size: 3rem;
  line-height: 1;
}
.sa-daily__actions {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  width: 100%;
  margin-top: 0.5rem;
}
</style>

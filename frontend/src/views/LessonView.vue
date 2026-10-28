<script setup lang="ts">
/**
 * LessonView — the LessonReader. Resolves the lesson id (generation store, else request status),
 * loads it, and renders the fixed 12-section skeleton mobile-first, single column:
 *   - learning objectives up top,
 *   - each section by ordinal: title, SafeContent(body_markdown), LessonAsset(s) in a dual-coding
 *     layout, and QuestionRenderer for the interactive kinds (pretest / practice /
 *     interleaved_review / misconception_check),
 *   - answers POST via api.submitAnswer (lesson-embedded => attempt_id null); feedback shows
 *     inline through QuestionRenderer's :feedback,
 *   - later interactive sections are GATED until earlier ones have been attempted,
 *   - a spaced-review preview + a growth-mindset closing message.
 * RESUME: the store restores the learner's revealed parts + answered questions from the server; this
 * view then puts the viewport back where they were reading (exact spot on this device, else the part
 * they had reached) and keeps that spot saved as they scroll.
 * The ROUTE decides which lesson opens (a lesson generated earlier in this tab never overrides it),
 * and nothing from a previously opened lesson is shown while this one loads.
 * A failed answer leaves the question answerable with a friendly toast; an answer the server met with
 * a support block (crisis net) shows that block instead of feedback, ungraded and still answerable.
 * All LLM output renders via SafeContent / LessonAsset (never raw v-html). WCAG 2.2 AA throughout.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import CrisisCard from '@/components/CrisisCard.vue'
import LessonAsset from '@/components/content/LessonAsset.vue'
import SafeContent from '@/components/content/SafeContent.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import SaButton from '@/components/common/SaButton.vue'
import SuggestionsStrip from '@/components/common/SuggestionsStrip.vue'
import { toast } from '@/components/common/useToasts'
import ReadAloudButton from '@/components/content/ReadAloudButton.vue'
import CorrectAnswer from '@/components/questions/CorrectAnswer.vue'
import { speechLang } from '@/lib/speechLang'
import QuestionRenderer from '@/components/questions/QuestionRenderer.vue'
import { useCelebration } from '@/composables/useCelebration'
import { api } from '@/lib/api'
import { answerErrorKey } from '@/lib/errors'
import { subjectLabel } from '@/lib/format'
import { levelLabel } from '@/lib/grades'
import { loadReadingAnchor, saveReadingAnchor } from '@/lib/readingAnchor'
import { useGenerationStore } from '@/stores/generation'
import { useLessonStore } from '@/stores/lesson'
import { usePrefsStore } from '@/stores/prefs'
import { useSessionStore } from '@/stores/session'
import type { AnswerEvent } from '@/types/question'
import type { AnswerSupport, LearningSessionSummary, LessonSection } from '@/types/session'

const props = defineProps<{ sessionId: string }>()
const { t } = useI18n()
const gen = useGenerationStore()
const lessonStore = useLessonStore()
const prefs = usePrefsStore()
const session = useSessionStore()
const { celebrateCorrect } = useCelebration()

const failed = ref(false)
const suggestions = ref<LearningSessionSummary[]>([])
// Set once this view is being torn down: async work that finishes later must not touch the page.
let leaving = false
// Support blocks (crisis net) per item id: shown in place of feedback, the question stays open.
const supportByItem = reactive<Record<number, AnswerSupport>>({})

const INTERACTIVE_KINDS = new Set([
  'pretest',
  'practice',
  'interleaved_review',
  'misconception_check',
])

// Only the lesson of THIS route: the store still holds the previously opened lesson until load()
// replaces it, and that must never flash up here.
const lesson = computed(() =>
  lessonStore.lesson?.request_id === props.sessionId ? lessonStore.lesson : null,
)

const sortedSections = computed<LessonSection[]>(() =>
  lesson.value ? [...lesson.value.sections].sort((a, b) => a.ordinal - b.ordinal) : [],
)

// --- progressive reveal with prefetch: the learner reveals one part at a time (`revealedUpTo`); the
// store silently pre-generates the NEXT part one ahead, so "Continue" is usually instant. A part that
// has been prefetched but not yet revealed is held back here until the learner advances.
function isReady(s: LessonSection): boolean {
  return (s.gen_status ?? 'ready') === 'ready'
}
const lastOrdinal = computed(() =>
  sortedSections.value.length ? sortedSections.value[sortedSections.value.length - 1].ordinal : 0,
)
const visibleSections = computed(() =>
  sortedSections.value.filter((s) => s.ordinal <= lessonStore.revealedUpTo && isReady(s)),
)
// The next part to reveal (if any) — drives the "Continue" card.
const nextOrdinal = computed<number | null>(() => {
  if (!lesson.value) return null
  const n = lessonStore.revealedUpTo + 1
  return n <= lastOrdinal.value ? n : null
})
const hasNext = computed(() => nextOrdinal.value !== null)
const allRevealed = computed(() => !hasNext.value && visibleSections.value.length > 0)

async function revealNext() {
  await lessonStore.revealNext()
  saveAnchor() // the boundary moved; keep the saved reading spot in step with it
}

function isInteractive(s: LessonSection): boolean {
  return INTERACTIVE_KINDS.has(s.kind) && s.items.length > 0
}

// Ordinals of interactive sections, in order — used to gate later ones until earlier are attempted.
const interactiveOrdinals = computed(() =>
  sortedSections.value.filter(isInteractive).map((s) => s.ordinal),
)

function sectionAttempted(s: LessonSection): boolean {
  return s.items.some((it) => lessonStore.feedbackByItem[it.id] != null)
}

/**
 * A section is locked if the backend marked it `gated`, OR (our progressive unlock) if it is an
 * interactive section preceded by an interactive section that has not yet been attempted.
 */
function isLocked(s: LessonSection): boolean {
  if (s.gated && !sectionAttempted(s)) {
    // Backend gate clears once the preceding interactive section is attempted. A gated FIRST
    // interactive section (idx <= 0) has no predecessor to attempt, so it must NOT be permanently
    // locked — fall through to the progressive-unlock branch (which returns false for idx <= 0).
    const idx = interactiveOrdinals.value.indexOf(s.ordinal)
    if (idx > 0) {
      const prevOrd = interactiveOrdinals.value[idx - 1]
      const prev = sortedSections.value.find((x) => x.ordinal === prevOrd)
      if (prev && !sectionAttempted(prev)) return true
    }
  }
  if (!isInteractive(s)) return false
  const idx = interactiveOrdinals.value.indexOf(s.ordinal)
  if (idx <= 0) return false
  const prevOrd = interactiveOrdinals.value[idx - 1]
  const prev = sortedSections.value.find((x) => x.ordinal === prevOrd)
  return !!prev && !sectionAttempted(prev)
}

const objectives = computed(() => lesson.value?.objectives ?? [])

// Read-aloud: each section's rendered text, in the lesson's language.
const sectionEls = ref<Record<number, HTMLElement | null>>({})
const readLang = computed(() => speechLang(lesson.value?.language, prefs.educationLocale))

// "Matematika · 4. třída · 15 min" — subject and level named the way the learner's school names them.
const crumbs = computed(() => {
  const l = lesson.value
  if (!l) return ''
  return [
    subjectLabel(l.subject),
    levelLabel(l, prefs.educationLocale),
    l.estimated_duration_min ? t('lesson.minutes', { n: l.estimated_duration_min }) : '',
  ]
    .filter(Boolean)
    .join(' · ')
})

// Questions whose answer is on its way. A double tap on Check (kids do) must not send it twice: the
// second request failed on the server, and the question stays locked until the grade is back.
const answering = reactive(new Set<number>())

async function onAnswer(e: AnswerEvent, target?: HTMLElement | null) {
  if (lessonStore.feedbackByItem[e.questionId] || answering.has(e.questionId)) return // graded / in flight
  answering.add(e.questionId)
  try {
    // Lesson-embedded practice => no quiz attempt (attempt_id null, per design).
    const res = await api.submitAnswer({ ...e, attemptId: null })
    if (res.support) {
      // Not graded, not recorded: show the help block, no "wrong" verdict, question stays open.
      supportByItem[e.questionId] = res.support
      return
    }
    lessonStore.recordAnswer(e.questionId, res)
    if (res.is_correct) void celebrateCorrect(target ?? null)
    if (res.xp_awarded) await session.refreshGamification().catch(() => {})
    session.applyStreak(res.streak) // every graded answer counts toward today, right or wrong
  } catch (err) {
    // The question stays answerable with the learner's input in place; say what happened.
    if (!leaving) toast.error(t(answerErrorKey(err)))
  } finally {
    answering.delete(e.questionId)
  }
}

// --- reading position: where on the page the learner is, kept on this device so a refresh or a
// return visit lands on the same line (the per-part position lives on the server — see the store).
// (Each part's card element — distinct from `sectionEls`, which holds the read-aloud text bodies.)
const sectionCards = new Map<number, HTMLElement>()
function setSectionCard(ordinal: number, el: unknown) {
  if (el instanceof HTMLElement) sectionCards.set(ordinal, el)
  else sectionCards.delete(ordinal)
}

// Off until the viewport has been placed, so the page loading at scroll 0 can't overwrite the spot.
let tracking = false
let saveTimer: ReturnType<typeof setTimeout> | null = null

function saveAnchor() {
  if (!tracking || !lesson.value) return
  // The part under the top edge of the viewport = the last revealed one that starts at/above it.
  let ordinal: number | null = null
  let offset = Math.round(window.scrollY)
  for (const s of visibleSections.value) {
    const top = sectionCards.get(s.ordinal)?.getBoundingClientRect().top
    if (top == null || top > 0) break
    ordinal = s.ordinal
    offset = Math.round(-top)
  }
  saveReadingAnchor({
    lessonId: lesson.value.id,
    revealedUpTo: lessonStore.revealedUpTo,
    ordinal,
    offset,
  })
}

function onScroll() {
  if (saveTimer) return
  saveTimer = setTimeout(() => {
    saveTimer = null
    saveAnchor()
  }, 300)
}

/** After a restore, put the learner back where they were reading. On this device that is the exact
 *  spot; otherwise (another device, or they have since moved on elsewhere) the part they had reached.
 *  A lesson they already finished reopens from the top. Always an instant jump, never an animation. */
async function placeViewport() {
  await nextTick() // the restored parts are in the DOM now
  if (leaving || !lesson.value) return
  const anchor = loadReadingAnchor(lesson.value.id)
  if (anchor && anchor.revealedUpTo === lessonStore.revealedUpTo) {
    const el = anchor.ordinal == null ? null : sectionCards.get(anchor.ordinal)
    if (anchor.ordinal == null) {
      window.scrollTo({ top: anchor.offset, behavior: 'instant' })
    } else if (el) {
      const top = window.scrollY + el.getBoundingClientRect().top + anchor.offset
      window.scrollTo({ top, behavior: 'instant' })
    }
  } else if (lessonStore.resumed && hasNext.value) {
    sectionCards
      .get(lessonStore.revealedUpTo)
      ?.scrollIntoView({ block: 'start', behavior: 'instant' })
  }
  if (lessonStore.resumed && hasNext.value) {
    toast.info(
      t('lesson.resumed', {
        current: visibleSections.value.length,
        total: sortedSections.value.length,
      }),
    )
  }
  tracking = true
}

/** The lesson id for THIS route. The generation store's id is used only when it was generated for
 *  this very request (the usual hop from the loading screen) — otherwise ask the server. */
async function resolveLessonId(): Promise<number | null> {
  if (gen.requestId === props.sessionId && gen.lessonId) return gen.lessonId
  return (await api.getRequestStatus(props.sessionId)).lesson_id
}

let listening = false
async function openLesson() {
  failed.value = false
  try {
    const id = await resolveLessonId()
    if (leaving) return
    if (!id) {
      failed.value = true
      return
    }
    await lessonStore.load(id)
    if (leaving) return
    await placeViewport()
    if (leaving || listening) return
    listening = true
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('pagehide', saveAnchor)
  } catch {
    if (!leaving) failed.value = true
  }
}

onMounted(async () => {
  await openLesson()
  // "More like this" picks for the closing — best-effort, never blocks the lesson.
  try {
    const recs = await api.getRecommendations({ requestId: props.sessionId, limit: 3 })
    if (!leaving) suggestions.value = recs
  } catch {
    /* recommendations are optional */
  }
})

// Leaving the reader: save the final reading spot while the page is still scrolled there (the
// router scrolls to the top right after), then stop listening. Anything still loading checks
// `leaving` when it lands, so no listener, toast or saved spot can appear after this.
onBeforeUnmount(() => {
  leaving = true
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('pagehide', saveAnchor)
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = null
  saveAnchor()
  tracking = false
})

// Stop any image-polling timers when leaving the reader (the store is a singleton).
onUnmounted(() => lessonStore.stopPolls())
</script>

<template>
  <article v-if="lesson" class="sa-lesson">
    <!-- Header -->
    <header class="sa-lesson__header">
      <p class="sa-lesson__crumbs">{{ crumbs }}</p>
      <h1 class="sa-lesson__title">{{ lesson.topic }}</h1>
    </header>

    <!-- Objectives -->
    <section v-if="objectives.length" class="sa-card sa-lesson__objectives">
      <h2 class="sa-lesson__h2">{{ t('lesson.objectives_title') }}</h2>
      <ul class="sa-lesson__obj-list">
        <li v-for="(o, i) in objectives" :key="i" class="sa-lesson__obj">
          <span class="sa-lesson__obj-tick" aria-hidden="true">★</span>
          <span>{{ o.text }}</span>
        </li>
      </ul>
    </section>

    <!-- Sections in order (only the parts the learner has revealed; the next is prefetched ahead) -->
    <section
      v-for="s in visibleSections"
      :key="s.ordinal"
      :ref="(el) => setSectionCard(s.ordinal, el)"
      class="sa-card sa-lesson__section"
      :class="{ 'sa-lesson__section--locked': isLocked(s) }"
      :aria-disabled="isLocked(s) ? 'true' : undefined"
    >
      <div class="sa-lesson__head">
        <h2 v-if="s.title" class="sa-lesson__h2">{{ s.title }}</h2>
        <ReadAloudButton v-if="!isLocked(s)" :target="sectionEls[s.ordinal] ?? null" :lang="readLang" />
      </div>

      <!-- Locked interactive section: explain why, don't reveal content. -->
      <p v-if="isLocked(s)" class="sa-lesson__locked-hint" role="note">
        <span aria-hidden="true">🔒</span> {{ t('lesson.gated_hint') }}
      </p>

      <template v-else>
        <!-- Dual coding: prose + visual side by side on wider screens, stacked on phones. -->
        <div
          :ref="(el) => (sectionEls[s.ordinal] = el as HTMLElement | null)"
          class="sa-lesson__body"
          :class="{ 'sa-lesson__body--dual': s.assets.length }"
        >
          <SafeContent
            v-if="s.body_markdown"
            :markdown="s.body_markdown"
            prose
            class="sa-lesson__prose"
          />
          <div v-if="s.assets.length" class="sa-lesson__assets">
            <LessonAsset
              v-for="(a, ai) in s.assets"
              :key="a.hash ?? `pending-${s.ordinal}-${ai}`"
              :asset="a"
              :eager="s.ordinal <= 2 && ai === 0"
            />
          </div>
        </div>

        <!-- Interactive items -->
        <div v-if="isInteractive(s)" class="sa-lesson__items">
          <div v-for="it in s.items" :key="it.id" class="sa-lesson__item">
            <QuestionRenderer
              :item="it"
              :feedback="lessonStore.feedbackByItem[it.id] ?? null"
              :disabled="!!lessonStore.feedbackByItem[it.id] || answering.has(it.id)"
              :submitted="lessonStore.submittedByItem[it.id]"
              :sound="prefs.sound"
              @answer="(e: AnswerEvent) => onAnswer(e)"
            />
            <CrisisCard
              v-if="supportByItem[it.id]"
              :message="supportByItem[it.id].message"
              :disclosure="supportByItem[it.id].disclosure"
              :resources="supportByItem[it.id].resources"
            />
            <CorrectAnswer :item="it" :feedback="lessonStore.feedbackByItem[it.id] ?? null" />
          </div>
        </div>
      </template>
    </section>

    <!-- Progressive reveal: the next part is prefetched one ahead, so "Continue" is usually instant. -->
    <section v-if="hasNext" class="sa-card sa-lesson__next" aria-live="polite">
      <template v-if="lessonStore.generatingOrdinal === nextOrdinal">
        <LoadingSpinner :size="32" :label="t('lesson.preparing_next')" />
        <p class="sa-lesson__next-hint">{{ t('lesson.preparing_next') }}</p>
      </template>
      <template v-else>
        <p class="sa-lesson__next-hint">{{ t('lesson.more_to_come') }}</p>
        <p
          v-if="lessonStore.failedOrdinal === nextOrdinal"
          class="sa-lesson__next-err"
          role="alert"
        >
          {{ t('lesson.next_error') }}
        </p>
        <SaButton
          variant="primary"
          icon="sparkle"
          :loading="lessonStore.generatingOrdinal !== null"
          @click="revealNext"
        >
          {{
            lessonStore.failedOrdinal === nextOrdinal
              ? t('common.retry')
              : t('lesson.continue_next')
          }}
        </SaButton>
      </template>
    </section>

    <!-- Spaced-review preview + closing appear once the whole lesson has been revealed. -->
    <template v-if="allRevealed">
      <section class="sa-card sa-lesson__review">
        <h2 class="sa-lesson__h2">
          <span aria-hidden="true">🔁</span> {{ t('lesson.review_title') }}
        </h2>
        <p class="text-[var(--color-ink-soft)]">{{ t('lesson.review_body') }}</p>
      </section>

      <!-- More like this (reuse existing lessons/quizzes) -->
      <SuggestionsStrip :items="suggestions" :title="t('results.similar')" />

      <!-- Growth-mindset closing + onward CTAs -->
      <section class="sa-lesson__close" role="note">
        <p class="sa-lesson__close-text">{{ t('lesson.closing') }}</p>
        <div class="sa-lesson__close-actions">
          <SaButton variant="primary" size="lg" block icon="star" :to="{ name: 'stats' }">
            {{ t('results.view_progress') }}
          </SaButton>
          <SaButton variant="ghost" block to="/" icon="sparkle">{{ t('lesson.learn_more') }}</SaButton>
        </div>
      </section>
    </template>
  </article>

  <EmptyState
    v-else-if="failed"
    icon="hint"
    :title="t('lesson.load_error_title')"
    :description="t('lesson.load_error_body')"
    announce
  >
    <SaButton variant="primary" icon="sparkle" @click="openLesson">{{ t('common.retry') }}</SaButton>
    <SaButton variant="ghost" to="/" icon="home">{{ t('common.back') }}</SaButton>
  </EmptyState>

  <div v-else class="sa-lesson__loading">
    <LoadingSpinner :size="40" :label="t('common.loading')" />
  </div>
</template>

<style scoped>
.sa-lesson__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.sa-lesson {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 1.25rem 0 3rem;
}
.sa-lesson__header {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.sa-lesson__crumbs {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--color-ink-soft);
}
.sa-lesson__title {
  font-size: clamp(1.6rem, 6vw, 2.1rem);
  font-weight: 800;
  line-height: 1.15;
}
.sa-lesson__h2 {
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0 0 0.6rem;
}
.sa-lesson__objectives,
.sa-lesson__section,
.sa-lesson__review {
  padding: 1.1rem;
}
.sa-lesson__section {
  /* Resuming scrolls a part into view; keep its title clear of the sticky header. */
  scroll-margin-top: 4.5rem;
}
.sa-lesson__obj-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.sa-lesson__obj {
  display: flex;
  gap: 0.55rem;
  align-items: flex-start;
}
.sa-lesson__obj-tick {
  color: var(--color-sun);
  flex: none;
  line-height: 1.5;
}
.sa-lesson__body--dual {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.sa-lesson__prose {
  /* readable measure handled by prose-reading on SafeContent */
  margin: 0;
}
.sa-lesson__assets {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.sa-lesson__items {
  margin-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.sa-lesson__section--locked {
  opacity: 0.92;
  background: var(--color-surface-2);
}
.sa-lesson__locked-hint {
  margin: 0;
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-lesson__review {
  border-left: 4px solid var(--color-sun);
}
.sa-lesson__next {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 1.25rem 1.1rem;
  text-align: center;
  border: 2px dashed var(--color-line);
}
.sa-lesson__next-hint {
  margin: 0;
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-lesson__next-err {
  margin: 0;
  font-weight: 600;
  color: var(--color-coral);
}
.sa-lesson__close {
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 0.5rem 0 1rem;
}
.sa-lesson__close-text {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--color-primary-strong);
}
.sa-lesson__close-actions {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.sa-lesson__loading {
  display: grid;
  place-items: center;
  padding: 4rem 0;
}
/* Dual-coding two-column layout from tablet up. */
@media (min-width: 768px) {
  .sa-lesson__body--dual {
    flex-direction: row;
    align-items: flex-start;
  }
  .sa-lesson__body--dual .sa-lesson__prose {
    flex: 1 1 60%;
  }
  .sa-lesson__body--dual .sa-lesson__assets {
    flex: 1 1 40%;
    max-width: 22rem;
  }
}
</style>

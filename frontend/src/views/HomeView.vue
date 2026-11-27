<script setup lang="ts">
/**
 * HomeView — the playful entry point. A dominant prompt hero (single textarea + big CTA),
 * example chips, and a link to /resume. Tasks a parent gave come first, as one compact list
 * (WaitingCard) — they are what is genuinely waiting; the hero question then sits right on its input.
 * The learner's own unfinished lesson/quiz is a quiet row below the box (ContinueRow): offered while
 * it is recent, hideable on this device. The code to continue elsewhere is one line at the bottom
 * (the full card, with the QR, is in Settings). On submit we lazily ensure an anonymous profile, then
 * route on the sanitizer Decision:
 *   proceed  -> /loading/:request_id (generation)
 *   clarify  -> inline clarifying question + suggestion chips that REFINE the prompt
 *   refuse   -> friendly inline redirect with alternative-topic chips
 *   crisis   -> dedicated, non-dismissable CrisisCard (resources + AI disclosure)
 * A compact line shows the learner's class (set in Settings) — prompts needn't name the grade, the
 * backend applies the class whenever a prompt names no level.
 * Tasks are re-read when the tab comes back, so one given meanwhile shows up. A device that follows
 * children as a parent gets a "For parents" link.
 * Mobile-first, WCAG 2.2 AA (>=44px targets, aria-live status, visible focus, never color-only).
 */
import { useDocumentVisibility } from '@vueuse/core'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import CrisisCard from '@/components/CrisisCard.vue'
import DailyReviewCard from '@/components/common/DailyReviewCard.vue'
import ResumeCodeCard from '@/components/common/ResumeCodeCard.vue'
import SaButton from '@/components/common/SaButton.vue'
import SaChip from '@/components/common/SaChip.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import SuggestionsStrip from '@/components/common/SuggestionsStrip.vue'
import ContinueRow from '@/components/tasks/ContinueRow.vue'
import WaitingCard from '@/components/tasks/WaitingCard.vue'
import { useReducedMotion } from '@/composables/useReducedMotion'
import { api } from '@/lib/api'
import { friendlyErrorKey } from '@/lib/errors'
import { isContinueHidden } from '@/lib/hiddenContinue'
import { MAX_PROMPT_CHARS } from '@/lib/limits'
import { schoolYearLabel } from '@/lib/grades'
import { useVoiceInput, voiceInputSupported } from '@/composables/useVoiceInput'
import { useParentStore } from '@/stores/parent'
import { usePrefsStore } from '@/stores/prefs'
import { usePromptStore } from '@/stores/prompt'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { Assignment, Decision, LearningSessionSummary } from '@/types/session'

const { t, tm } = useI18n()
const router = useRouter()
const session = useSessionStore()
const prompt = usePromptStore()
const prefs = usePrefsStore()
const ui = useUiStore()
const parent = useParentStore()
const { reduced } = useReducedMotion()

const text = ref('')
const busy = ref(false)
const errorMsg = ref<string | null>(null)
const decision = ref<Decision | null>(null)
const promptEl = ref<HTMLTextAreaElement | null>(null)
const suggestions = ref<LearningSessionSummary[]>([])
// The unfinished lesson/quiz the learner was last in. Opening it restores their exact position.
const unfinished = ref<LearningSessionSummary | null>(null)
// Tasks a parent gave, not finished yet. Each session is listed once: a started task stays in the
// task card (not in the continue row), and the suggestions leave out what either shows.
const tasks = ref<Assignment[]>([])
const taskIds = computed(() => new Set(tasks.value.map((a) => a.request_id)))
// The continue row: the unfinished session, unless it is a task (listed above) or hidden here.
const continueRow = computed(() => {
  const u = unfinished.value
  if (!u?.progress || taskIds.value.has(u.request_id) || isContinueHidden(u)) return null
  return u
})
// Don't list the same session twice (it already has a row above).
const otherSuggestions = computed(() =>
  suggestions.value.filter(
    (s) => s.request_id !== unfinished.value?.request_id && !taskIds.value.has(s.request_id),
  ),
)

// This device follows children as a parent → one tap to their overview (names only on this device).
const followedNames = computed(() =>
  parent.children.map((c, i) => c.name || t('parent.child_fallback', { n: i + 1 })).join(', '),
)

async function loadTasks(): Promise<Assignment[]> {
  return api.getMyAssignments()
}

// Returning learners (a saved resume code) get their unfinished session to continue, plus a strip of
// ready lessons/quizzes to explore — reuse over regenerating the same topic. Best-effort; silent on
// failure.
onMounted(async () => {
  if (!session.resumeCode) return
  const [cont, recs, given] = await Promise.allSettled([
    api.getContinue(),
    api.getRecommendations({ limit: 4 }),
    loadTasks(),
  ])
  if (cont.status === 'fulfilled') unfinished.value = cont.value
  if (recs.status === 'fulfilled') suggestions.value = recs.value
  if (given.status === 'fulfilled') tasks.value = given.value
})

// A parent may give a task while this screen waits in the background (a tablet left on Home).
const visibility = useDocumentVisibility()
watch(visibility, async (v) => {
  if (v !== 'visible' || !session.resumeCode) return
  try {
    tasks.value = await loadTasks()
  } catch {
    /* keep what is shown */
  }
})

// Example prompts are localized (array). Fall back gracefully if a locale lacks them.
const examples = computed<string[]>(() => {
  const raw = tm('home.example_list') as unknown
  return Array.isArray(raw) ? (raw as string[]) : []
})
// A few ideas at a time (a different few each visit; "Other ideas" moves on) rather than the whole
// list, one per line, below the box.
const IDEAS_SHOWN = 3
const ideaStart = ref(Math.floor(Math.random() * 1000))
const ideas = computed(() => {
  const list = examples.value
  if (list.length <= IDEAS_SHOWN) return list
  return Array.from({ length: IDEAS_SHOWN }, (_, i) => list[(ideaStart.value + i) % list.length])
})
function moreIdeas() {
  ideaStart.value += IDEAS_SHOWN
}

const canSubmit = computed(() => text.value.trim().length > 0 && !busy.value)

// --- dictation (parent opt-in in Settings) ---
const canDictate = computed(() => prefs.voiceInput && voiceInputSupported())
const voice = useVoiceInput((said) => {
  text.value = text.value.trim() ? `${text.value.trim()} ${said}` : said
})
function toggleDictation() {
  if (voice.listening.value) voice.stop()
  else voice.start(prefs.educationLocale ?? 'cs-CZ')
}

// --- the learner's class lives in Settings; home only shows it (or invites to set it) ---
const gradeName = computed(() =>
  prefs.schoolYear === null ? '' : schoolYearLabel(prefs.schoolYear, prefs.educationLocale),
)

const isClarify = computed(() => decision.value?.type === 'clarify')
const isRefuse = computed(() => decision.value?.type === 'refuse')
const isCrisis = computed(() => decision.value?.type === 'crisis')

async function go() {
  if (!canSubmit.value) return
  busy.value = true
  errorMsg.value = null
  try {
    await session.ensureProfile()
    const d = await prompt.submit(text.value.trim())
    decision.value = d
    if (d.type === 'proceed') {
      router.push({ name: 'loading', params: { sessionId: d.request_id } })
    }
    // clarify / refuse / crisis stay on this view and render inline below.
  } catch (e) {
    // Never the raw error: a friendly, localized reason. When the learner's own profile couldn't be
    // loaded, the app-wide "can't reach the server" banner (with Retry) already says so — and their
    // code is kept; the "Let's go!" button here retries too.
    errorMsg.value = session.unreachable ? null : t(friendlyErrorKey(e))
  } finally {
    busy.value = false
  }
}

function useExample(ex: string) {
  text.value = ex
  decision.value = null
  errorMsg.value = null
  nextTick(() => promptEl.value?.focus())
}

/** A clarify suggestion refines the prompt: append the suggestion and re-submit. */
function applyClarification(suggestion: string) {
  const base = prompt.raw || text.value
  text.value = `${base} — ${suggestion}`.trim()
  decision.value = null
  go()
}

/** A refuse redirect replaces the prompt with a friendly alternative and focuses for editing. */
function applyRedirect(suggestion: string) {
  useExample(suggestion)
}
</script>

<template>
  <section class="flex flex-col gap-6 py-8 sm:py-10">
    <!-- What is waiting comes first (not while the crisis card takes over: nothing else is actionable). -->
    <template v-if="!isCrisis">
      <!-- This device follows children as a parent: straight to their overview and tasks. -->
      <RouterLink v-if="parent.children.length" :to="{ name: 'parent' }" class="sa-card sa-home__parent">
        <span class="sa-home__progress-icon" aria-hidden="true"><SaIcon name="users" :size="20" /></span>
        <span class="sa-home__parent-text">
          <span class="sa-home__parent-title">{{ t('parent.home_link', { names: followedNames }) }}</span>
          <span class="sa-home__parent-hint">{{ t('parent.home_link_hint') }}</span>
        </span>
        <SaIcon name="back" :size="16" class="sa-home__progress-chevron" aria-hidden="true" />
      </RouterLink>

      <!-- Tasks from a parent: one list, one tap each (renders nothing without any). -->
      <WaitingCard :tasks="tasks" />
    </template>

    <!-- Hero: the question, right above its input -->
    <header class="text-center">
      <p class="sa-hero__eyebrow">
        <span aria-hidden="true">✦</span> {{ t('app.tagline') }}
      </p>
      <h1 id="sa-home-title" class="sa-hero__title">{{ t('home.hero_title') }}</h1>
      <p class="mt-2 text-[var(--color-ink-soft)]">{{ t('home.hero_subtitle') }}</p>
    </header>

    <!-- Crisis takes over the whole flow: nothing else is actionable. -->
    <CrisisCard
      v-if="isCrisis && decision && decision.type === 'crisis'"
      :message="decision.message"
      :disclosure="decision.disclosure"
      :resources="decision.resources"
    />

    <template v-else>
      <!-- Prompt hero card -->
      <form class="sa-card sa-prompt" :class="{ 'sa-prompt--anim': !reduced }" @submit.prevent="go">
        <!-- The hero question above is the visible label; this one is for screen readers. -->
        <label for="prompt" class="sr-only">{{ t('home.prompt_label') }}</label>
        <textarea
          id="prompt"
          ref="promptEl"
          v-model="text"
          rows="3"
          :maxlength="MAX_PROMPT_CHARS"
          :placeholder="t('home.prompt_placeholder')"
          :aria-describedby="errorMsg ? 'prompt-error' : undefined"
          class="sa-prompt__input"
          @keydown.enter.exact.prevent="go"
        />
        <button
          v-if="canDictate"
          type="button"
          class="sa-prompt__mic"
          :aria-pressed="voice.listening.value"
          @click="toggleDictation"
        >
          <span aria-hidden="true">{{ voice.listening.value ? '⏹' : '🎤' }}</span>
          {{ voice.listening.value ? t('speech.listening') : t('speech.dictate') }}
        </button>
        <SaButton
          type="submit"
          variant="primary"
          size="lg"
          block
          icon="sparkle"
          :loading="busy"
          :disabled="!canSubmit"
        >
          {{ busy ? t('home.go_busy') : t('home.go') }}
        </SaButton>
        <p class="sa-prompt__hint">{{ t('home.enter_hint') }}</p>
        <p class="sa-prompt__grade">
          <span aria-hidden="true">🎒</span>
          <template v-if="gradeName">{{ t('home.grade_for', { grade: gradeName }) }}</template>
          <button
            type="button"
            class="sa-prompt__grade-change"
            :class="{ 'sa-prompt__grade-set': !gradeName }"
            @click="ui.settingsOpen = true"
          >
            {{ gradeName ? t('home.grade_change') : t('home.grade_set') }}
          </button>
        </p>

        <p
          v-if="errorMsg"
          id="prompt-error"
          class="sa-prompt__error"
          role="alert"
        >
          {{ errorMsg }}
        </p>
      </form>

      <!-- Clarify: show the question + refining suggestion chips. -->
      <div
        v-if="isClarify && decision && decision.type === 'clarify'"
        class="sa-card sa-aside sa-aside--clarify"
        role="status"
        aria-live="polite"
      >
        <p class="sa-aside__title">
          <span aria-hidden="true">🤔</span> {{ decision.question }}
        </p>
        <div v-if="decision.suggestions.length" class="sa-aside__chips">
          <SaChip
            v-for="s in decision.suggestions"
            :key="s"
            tone="primary"
            clickable
            @click="applyClarification(s)"
          >
            {{ s }}
          </SaChip>
        </div>
      </div>

      <!-- Refuse: friendly redirect with alternative topic chips. -->
      <div
        v-if="isRefuse && decision && decision.type === 'refuse'"
        class="sa-card sa-aside sa-aside--refuse"
        role="status"
        aria-live="polite"
      >
        <p class="sa-aside__title">
          <span aria-hidden="true">💡</span> {{ decision.reason }}
        </p>
        <p class="sa-aside__sub">{{ t('home.refuse_try') }}</p>
        <div v-if="decision.redirect_suggestions.length" class="sa-aside__chips">
          <SaChip
            v-for="s in decision.redirect_suggestions"
            :key="s"
            tone="info"
            clickable
            @click="applyRedirect(s)"
          >
            {{ s }}
          </SaChip>
        </div>
      </div>

      <!-- The lesson/quiz they were last in (recent, not a task, not hidden on this device). -->
      <ContinueRow v-if="continueRow" :key="continueRow.request_id" :session="continueRow" />

      <!-- Today's spaced-repetition round (renders only when something is due). -->
      <DailyReviewCard />

      <!-- Ideas: a few at a time; tapping one puts it in the box to edit or send -->
      <section v-if="ideas.length" class="sa-ideas" aria-labelledby="sa-ideas-title">
        <div class="sa-ideas__head">
          <h2 id="sa-ideas-title" class="sa-ideas__title">{{ t('home.examples') }}</h2>
          <button v-if="examples.length > IDEAS_SHOWN" type="button" class="sa-ideas__more" @click="moreIdeas">
            <span aria-hidden="true">🎲</span> {{ t('home.more_ideas') }}
          </button>
        </div>
        <div class="sa-ideas__chips" aria-live="polite">
          <SaChip v-for="ex in ideas" :key="ex" icon="sparkle" clickable @click="useExample(ex)">
            {{ ex }}
          </SaChip>
        </div>
      </section>

      <!-- Ready lessons/quizzes to explore (returning learners), with a path to the full list. -->
      <template v-if="otherSuggestions.length">
        <SuggestionsStrip :items="otherSuggestions" :title="t('home.continue_title')" />
        <RouterLink :to="{ name: 'history' }" class="sa-home__seeall">
          <SaIcon name="books" :size="16" aria-hidden="true" />
          {{ t('history.title') }}
        </RouterLink>
      </template>

      <!-- Progress entry as a tidy card row — only as a fallback when the header cluster isn't yet
           showing the gamification snapshot (avoids a duplicate route to /stats on one screen). -->
      <RouterLink
        v-if="session.resumeCode && !session.gamification"
        :to="{ name: 'stats' }"
        class="sa-card sa-home__progress"
      >
        <span class="sa-home__progress-icon" aria-hidden="true"><SaIcon name="star" :size="20" /></span>
        <span class="sa-home__progress-label">{{ t('stats.title') }}</span>
        <SaIcon name="back" :size="16" class="sa-home__progress-chevron" aria-hidden="true" />
      </RouterLink>

      <!-- Once a profile exists, show the learner THEIR code to save (one line; the full card with
           the QR is in Settings); otherwise offer to enter one. -->
      <ResumeCodeCard v-if="session.resumeCode" line />
      <RouterLink v-else to="/resume" class="sa-home__resume">
        {{ t('home.have_code') }}
      </RouterLink>
    </template>
  </section>
</template>

<style scoped>
.sa-hero__eyebrow {
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-primary);
}
.sa-hero__title {
  margin-top: 0.35rem;
  font-size: clamp(1.9rem, 7vw, 2.6rem);
  font-weight: 800;
  line-height: 1.1;
  background: linear-gradient(120deg, var(--color-primary), var(--color-accent));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.sa-prompt {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 1.1rem;
}
.sa-prompt--anim {
  animation: sa-rise 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}
.sa-prompt__input {
  width: 100%;
  resize: none;
  border-radius: var(--radius-btn);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  padding: 0.85rem;
  font: inherit;
  font-size: 1.05rem;
  line-height: 1.5;
  color: var(--color-ink);
}
.sa-prompt__input:focus {
  outline: none;
  border-color: var(--color-primary);
  background: var(--color-surface);
}
.sa-prompt__hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-ink-soft);
}
/* "Press Enter…" means nothing on a touch screen's keyboard. */
@media (hover: none), (pointer: coarse) {
  .sa-prompt__hint {
    display: none;
  }
}
.sa-ideas {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.sa-ideas__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.sa-ideas__title {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--color-ink-soft);
}
.sa-ideas__more {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  min-height: var(--tap-min);
  padding: 0 0.6rem;
  border: 0;
  border-radius: var(--radius-pill);
  background: none;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--color-primary);
  cursor: pointer;
}
.sa-ideas__more:hover {
  background: var(--color-surface-2);
}
.sa-ideas__more:focus-visible {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
}
.sa-ideas__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.sa-prompt__mic {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: var(--tap-min);
  padding: 0.35rem 0.9rem;
  border-radius: var(--radius-pill);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  font: inherit;
  font-weight: 700;
  color: var(--color-ink);
  cursor: pointer;
}
.sa-prompt__mic[aria-pressed='true'] {
  border-color: var(--color-coral);
}
/* No class yet: an inviting pill rather than a small link (it is what makes content fit). */
.sa-prompt__grade-set {
  padding: 0.35rem 0.9rem;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-sun) 22%, var(--color-surface));
  text-decoration: none;
  color: var(--color-ink);
  font-weight: 700;
}
.sa-prompt__grade {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}
.sa-prompt__grade-change {
  min-height: var(--tap-min);
  padding: 0 0.4rem;
  border: 0;
  background: none;
  font: inherit;
  font-weight: 600;
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.sa-prompt__error {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-coral);
}
.sa-aside {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  padding: 1rem 1.1rem;
}
.sa-aside--clarify {
  border-left: 4px solid var(--color-primary);
}
.sa-aside--refuse {
  border-left: 4px solid var(--color-sky);
}
.sa-aside__title {
  margin: 0;
  font-weight: 700;
  line-height: 1.45;
}
.sa-aside__sub {
  margin: 0;
  font-size: 0.9rem;
  color: var(--color-ink-soft);
}
.sa-aside__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.sa-home__resume {
  align-self: center;
  color: var(--color-primary);
  font-size: 0.95rem;
  text-decoration: underline;
  text-underline-offset: 2px;
  min-height: var(--tap-min);
  display: inline-flex;
  align-items: center;
}
.sa-home__progress {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.7rem 0.85rem;
  min-height: var(--tap-min);
  border: 2px solid var(--color-line);
  font-weight: 700;
  color: var(--color-ink);
}
.sa-home__progress-icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 2.1rem;
  height: 2.1rem;
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
  color: var(--color-primary);
}
.sa-home__progress-label {
  flex: 1;
  min-width: 0;
}
.sa-home__progress-chevron {
  flex-shrink: 0;
  transform: rotate(180deg);
  color: var(--color-ink-soft);
}
.sa-home__parent {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.7rem 0.85rem;
  min-height: var(--tap-min);
  border: 2px solid var(--color-line);
  color: var(--color-ink);
}
.sa-home__parent-text {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}
.sa-home__parent-title {
  font-weight: 700;
  overflow-wrap: anywhere;
}
.sa-home__parent-hint {
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-home__seeall {
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: var(--tap-min);
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-ink-soft);
  text-decoration: underline;
  text-underline-offset: 2px;
}
@keyframes sa-rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
:root[data-reduced-motion='true'] .sa-prompt--anim {
  animation: none;
}
</style>

<script setup lang="ts">
/**
 * HomeView — the playful entry point. A dominant prompt hero (single textarea + big CTA),
 * example chips, and a link to /resume. On submit we lazily ensure an anonymous profile, then
 * route on the sanitizer Decision:
 *   proceed  -> /loading/:request_id (generation)
 *   clarify  -> inline clarifying question + suggestion chips that REFINE the prompt
 *   refuse   -> friendly inline redirect with alternative-topic chips
 *   crisis   -> dedicated, non-dismissable CrisisCard (resources + AI disclosure)
 * Mobile-first, WCAG 2.2 AA (>=44px targets, aria-live status, visible focus, never color-only).
 */
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import CrisisCard from '@/components/CrisisCard.vue'
import ResumeCodeCard from '@/components/common/ResumeCodeCard.vue'
import SaButton from '@/components/common/SaButton.vue'
import SaChip from '@/components/common/SaChip.vue'
import { useReducedMotion } from '@/composables/useReducedMotion'
import { usePromptStore } from '@/stores/prompt'
import { useSessionStore } from '@/stores/session'
import type { Decision } from '@/types/session'

const { t, tm } = useI18n()
const router = useRouter()
const session = useSessionStore()
const prompt = usePromptStore()
const { reduced } = useReducedMotion()

const text = ref('')
const busy = ref(false)
const errorMsg = ref<string | null>(null)
const decision = ref<Decision | null>(null)
const promptEl = ref<HTMLTextAreaElement | null>(null)

// Example prompts are localized (array). Fall back gracefully if a locale lacks them.
const examples = computed<string[]>(() => {
  const raw = tm('home.example_list') as unknown
  return Array.isArray(raw) ? (raw as string[]) : []
})

const canSubmit = computed(() => text.value.trim().length > 0 && !busy.value)

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
    errorMsg.value = e instanceof Error ? e.message : t('home.generic_error')
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
    <!-- Hero -->
    <header class="text-center">
      <p class="sa-hero__eyebrow">
        <span aria-hidden="true">✦</span> {{ t('app.tagline') }}
      </p>
      <h1 class="sa-hero__title">{{ t('home.hero_title') }}</h1>
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
        <label for="prompt" class="sa-prompt__label">{{ t('home.prompt_label') }}</label>
        <textarea
          id="prompt"
          ref="promptEl"
          v-model="text"
          rows="3"
          :placeholder="t('home.prompt_placeholder')"
          :aria-describedby="errorMsg ? 'prompt-error' : undefined"
          class="sa-prompt__input"
          @keydown.enter.exact.prevent="go"
        />
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

      <!-- Example prompts -->
      <div v-if="examples.length" class="flex flex-col gap-2">
        <p class="text-sm font-semibold text-[var(--color-ink-soft)]">
          {{ t('home.examples') }}
        </p>
        <div class="flex flex-wrap gap-2">
          <SaChip
            v-for="ex in examples"
            :key="ex"
            icon="sparkle"
            clickable
            @click="useExample(ex)"
          >
            {{ ex }}
          </SaChip>
        </div>
      </div>

      <!-- Once a profile exists, show the learner THEIR code to save; otherwise offer to enter one. -->
      <ResumeCodeCard v-if="session.resumeCode" />
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
.sa-prompt__label {
  font-size: 1.05rem;
  font-weight: 700;
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

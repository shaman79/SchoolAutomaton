<script setup lang="ts">
/**
 * A parent gives a task: what to learn (free text, checked by the server exactly like the child's
 * own prompt) and whether it should be a lesson or a quiz. On a go-ahead the task is created and
 * prepared at once (emits `given`). Otherwise the server's answer is shown right here, as on the
 * child's home screen: a question with suggestions that refine the text (clarify), a friendly
 * redirect (refuse), or the support card (crisis). Mobile-first, WCAG 2.2 AA.
 */
import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import CrisisCard from '@/components/CrisisCard.vue'
import SaButton from '@/components/common/SaButton.vue'
import SaChip from '@/components/common/SaChip.vue'
import { useReducedMotion } from '@/composables/useReducedMotion'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/apiError'
import { parentErrorKey } from '@/lib/errors'
import { MAX_PROMPT_CHARS } from '@/lib/limits'
import type { Assignment, Decision, Mode } from '@/types/session'

const props = defineProps<{ code: string; gradeLabel: string; maxOpen: number }>()
const emit = defineEmits<{
  (e: 'given', task: Assignment): void
  (e: 'cancel'): void
  (e: 'revoked'): void
}>()

const { t } = useI18n()

const text = ref('')
const mode = ref<Mode>('study')
const busy = ref(false)
const error = ref<string | null>(null)
const decision = ref<Decision | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)
const answerEl = ref<HTMLElement | null>(null)
const { reduced } = useReducedMotion()
const uid = Math.random().toString(36).slice(2, 8)

/** Open with a suggestion (e.g. a topic worth practising) — the parent can still edit it. */
function prefill(value: string, kind: Mode): void {
  text.value = value
  mode.value = kind
  decision.value = null
  error.value = null
  void focus()
}

async function focus(): Promise<void> {
  await nextTick()
  inputEl.value?.focus()
}

defineExpose({ prefill, focus })

async function submit(): Promise<void> {
  const prompt = text.value.trim()
  if (!prompt || busy.value) return
  busy.value = true
  error.value = null
  try {
    const res = await api.parentAssign(props.code, prompt, mode.value)
    if (res.assignment) {
      decision.value = null
      text.value = ''
      emit('given', res.assignment)
    } else {
      decision.value = res.decision
      // The answer appears under the form — on a phone that is below the screen's edge.
      await nextTick()
      answerEl.value?.scrollIntoView({ behavior: reduced.value ? 'auto' : 'smooth', block: 'nearest' })
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) emit('revoked')
    else if (e instanceof ApiError && e.status === 409) error.value = t('parent.too_many', { n: props.maxOpen })
    else error.value = t(parentErrorKey(e))
  } finally {
    busy.value = false
  }
}

/** A clarify suggestion refines the text and asks again (as on the child's home screen). */
function refine(suggestion: string): void {
  text.value = `${text.value.trim()} — ${suggestion}`.trim()
  void submit()
}

/** A refuse redirect replaces the text, to be checked and sent by the parent. */
function replaceWith(suggestion: string): void {
  text.value = suggestion
  decision.value = null
  void focus()
}
</script>

<template>
  <div class="sa-compose">
    <form class="sa-compose__form" @submit.prevent="submit">
      <label :for="`compose-${uid}`" class="sa-compose__label">{{ t('parent.composer_label') }}</label>
      <textarea
        :id="`compose-${uid}`"
        ref="inputEl"
        v-model="text"
        rows="2"
        :maxlength="MAX_PROMPT_CHARS"
        :placeholder="t('parent.composer_placeholder')"
        :aria-describedby="error ? `compose-err-${uid}` : `compose-hint-${uid}`"
        class="sa-compose__input"
        @keydown.enter.exact.prevent="submit"
      />

      <fieldset class="sa-compose__modes">
        <legend class="sa-compose__label">{{ t('parent.mode_label') }}</legend>
        <label v-for="m in (['study', 'test'] as const)" :key="m" class="sa-compose__mode">
          <input v-model="mode" type="radio" :name="`mode-${uid}`" :value="m" class="sa-compose__radio" />
          <span class="sa-compose__mode-body">
            <span class="sa-compose__mode-name">{{ t(m === 'test' ? 'parent.mode_test' : 'parent.mode_study') }}</span>
            <span class="sa-compose__mode-hint">
              {{ t(m === 'test' ? 'parent.mode_test_hint' : 'parent.mode_study_hint') }}
            </span>
          </span>
        </label>
      </fieldset>

      <p :id="`compose-hint-${uid}`" class="sa-compose__hint">
        {{ gradeLabel ? t('parent.composer_grade', { grade: gradeLabel }) : t('parent.composer_no_grade') }}
      </p>
      <p v-if="error" :id="`compose-err-${uid}`" class="sa-compose__error" role="alert">{{ error }}</p>

      <div class="sa-compose__actions">
        <SaButton type="submit" variant="primary" icon="sparkle" :loading="busy" :disabled="!text.trim() || busy">
          {{ busy ? t('parent.submitting') : t('parent.submit') }}
        </SaButton>
        <SaButton variant="ghost" :disabled="busy" @click="emit('cancel')">{{ t('parent.cancel') }}</SaButton>
      </div>
    </form>

    <div ref="answerEl" class="sa-compose__answer">
    <CrisisCard
      v-if="decision?.type === 'crisis'"
      :message="decision.message"
      :disclosure="decision.disclosure"
      :resources="decision.resources"
    />
    <div v-else-if="decision?.type === 'clarify'" class="sa-compose__aside" role="status" aria-live="polite">
      <p class="sa-compose__aside-title"><span aria-hidden="true">🤔</span> {{ decision.question }}</p>
      <div v-if="decision.suggestions.length" class="sa-compose__chips">
        <SaChip v-for="s in decision.suggestions" :key="s" tone="primary" clickable @click="refine(s)">{{ s }}</SaChip>
      </div>
    </div>
    <div v-else-if="decision?.type === 'refuse'" class="sa-compose__aside" role="status" aria-live="polite">
      <p class="sa-compose__aside-title"><span aria-hidden="true">💡</span> {{ decision.reason }}</p>
      <template v-if="decision.redirect_suggestions.length">
        <p class="sa-compose__hint">{{ t('parent.refuse_try') }}</p>
        <div class="sa-compose__chips">
          <SaChip v-for="s in decision.redirect_suggestions" :key="s" tone="info" clickable @click="replaceWith(s)">
            {{ s }}
          </SaChip>
        </div>
      </template>
    </div>
    </div>
  </div>
</template>

<style scoped>
.sa-compose {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.sa-compose__form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.sa-compose__label {
  font-weight: 700;
}
.sa-compose__input {
  width: 100%;
  resize: none;
  border-radius: var(--radius-btn);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  padding: 0.75rem;
  font: inherit;
  font-size: 1.05rem;
  line-height: 1.5;
  color: var(--color-ink);
}
.sa-compose__input:focus {
  outline: none;
  border-color: var(--color-primary);
  background: var(--color-surface);
}
.sa-compose__modes {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  border: 0;
}
.sa-compose__modes legend {
  margin-bottom: 0.5rem;
  padding: 0;
}
@media (min-width: 30rem) {
  .sa-compose__modes {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
/* Each kind is a whole card to tap; the chosen one gets a thick border + a filled radio dot. */
.sa-compose__mode {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  min-height: var(--tap-min);
  padding: 0.7rem 0.8rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
  cursor: pointer;
}
.sa-compose__mode:has(.sa-compose__radio:checked) {
  border-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface));
}
.sa-compose__mode:has(.sa-compose__radio:focus-visible) {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
}
.sa-compose__radio {
  flex: none;
  width: 1.2rem;
  height: 1.2rem;
  margin: 0.15rem 0 0;
  accent-color: var(--color-primary);
}
.sa-compose__mode-body {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.sa-compose__mode-name {
  font-weight: 800;
}
.sa-compose__mode-hint,
.sa-compose__hint {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.4;
  color: var(--color-ink-soft);
}
.sa-compose__error {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-coral);
}
.sa-compose__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.sa-compose__actions > :first-child {
  flex: 1 1 12rem;
}
.sa-compose__answer:empty {
  display: none;
}
.sa-compose__aside {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.85rem 1rem;
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-btn);
  background: var(--color-surface-2);
}
.sa-compose__aside-title {
  margin: 0;
  font-weight: 700;
  line-height: 1.45;
}
.sa-compose__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>

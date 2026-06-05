<script setup lang="ts">
/**
 * ResumeView — frictionless anonymous continue. Enter the 8-char resume code (auto-formatted
 * with the dash group) to re-adopt a server profile. If the device already has a freshly created
 * code, we surface it so the learner can save it. Mobile-first, WCAG 2.2 AA.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import SaButton from '@/components/common/SaButton.vue'
import { toast } from '@/components/common/useToasts'
import { useSessionStore } from '@/stores/session'

const { t } = useI18n()
const router = useRouter()
const session = useSessionStore()

const code = ref('')
const error = ref<string | null>(null)
const busy = ref(false)

// Surface a just-created code (shown once) so the learner can copy/save it.
const savedCode = computed(() => session.lastResumeCodeForDisplay)

const canSubmit = computed(() => code.value.trim().length > 0 && !busy.value)

async function go() {
  if (!canSubmit.value) return
  busy.value = true
  error.value = null
  try {
    await session.resumeWithCode(code.value.trim())
    router.push({ name: 'home' })
  } catch {
    error.value = t('resume.not_found')
  } finally {
    busy.value = false
  }
}

async function copySaved() {
  if (!savedCode.value) return
  try {
    await navigator.clipboard.writeText(savedCode.value)
    toast.success(t('resume.copied'))
  } catch {
    /* clipboard unavailable — code is visible to copy manually */
  }
}
</script>

<template>
  <section class="sa-resume">
    <h1 class="sa-resume__title">{{ t('resume.title') }}</h1>

    <!-- Just-created code reminder -->
    <div v-if="savedCode" class="sa-card sa-resume__saved" role="status">
      <p class="sa-resume__saved-label">{{ t('resume.your_code') }}</p>
      <p class="sa-resume__code">{{ savedCode }}</p>
      <SaButton variant="ghost" size="sm" icon="check" @click="copySaved">
        {{ t('resume.copy') }}
      </SaButton>
      <p class="sa-resume__saved-hint">{{ t('resume.save_hint') }}</p>
    </div>

    <form class="sa-card sa-resume__form" @submit.prevent="go">
      <label for="code" class="sa-resume__form-label">{{ t('resume.label') }}</label>
      <input
        id="code"
        v-model="code"
        autocomplete="off"
        autocapitalize="characters"
        spellcheck="false"
        inputmode="text"
        placeholder="K7QF-2M9X"
        :aria-describedby="error ? 'resume-error' : 'resume-hint'"
        class="sa-resume__input"
      />
      <SaButton type="submit" variant="primary" block :loading="busy" :disabled="!canSubmit">
        {{ t('resume.submit') }}
      </SaButton>
      <p v-if="error" id="resume-error" class="sa-resume__error" role="alert">{{ error }}</p>
      <p id="resume-hint" class="sa-resume__hint">{{ t('resume.save_hint') }}</p>
    </form>

    <RouterLink to="/" class="sa-resume__back">{{ t('common.back') }}</RouterLink>
  </section>
</template>

<style scoped>
.sa-resume {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  padding: 2.5rem 0 3rem;
}
.sa-resume__title {
  text-align: center;
  font-size: 1.6rem;
  font-weight: 800;
}
.sa-resume__saved {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1.1rem;
  text-align: center;
  border: 2px solid var(--color-mint);
  background: color-mix(in srgb, var(--color-mint) 8%, var(--color-surface));
}
.sa-resume__saved-label {
  margin: 0;
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-ink-soft);
}
.sa-resume__code {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  font-variant-numeric: tabular-nums;
}
.sa-resume__saved-hint {
  margin: 0;
  font-size: 0.8rem;
  color: var(--color-ink-soft);
}
.sa-resume__form {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 1.1rem;
}
.sa-resume__form-label {
  font-weight: 700;
}
.sa-resume__input {
  width: 100%;
  border-radius: var(--radius-btn);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  padding: 0.85rem;
  text-align: center;
  font: inherit;
  font-size: 1.25rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--color-ink);
}
.sa-resume__input:focus {
  outline: none;
  border-color: var(--color-primary);
  background: var(--color-surface);
}
.sa-resume__error {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-coral);
}
.sa-resume__hint {
  margin: 0;
  font-size: 0.8rem;
  color: var(--color-ink-soft);
}
.sa-resume__back {
  align-self: center;
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
  min-height: var(--tap-min);
  display: inline-flex;
  align-items: center;
}
</style>

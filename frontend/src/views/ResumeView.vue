<script setup lang="ts">
/**
 * ResumeView — frictionless anonymous continue. Enter the 8-char resume code (or open a shared
 * `/resume?code=…` link) to re-adopt a server profile.
 *
 * A device's code IS its learner's progress, so it is never replaced silently: when this device
 * already learns with a DIFFERENT code, we first show that current code (to write down / copy) and
 * ask before switching. A device with no code yet resumes straight away (one tap for a parent's
 * phone). The device's own code is shown here so it can be saved. Mobile-first, WCAG 2.2 AA.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import SaButton from '@/components/common/SaButton.vue'
import { toast } from '@/components/common/useToasts'
import { friendlyErrorKey } from '@/lib/errors'
import { formatResumeCode, normalizeResumeCode, useSessionStore } from '@/stores/session'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const code = ref('')
const error = ref<string | null>(null)
const busy = ref(false)
/** A different code waiting for "yes, switch" (this device already has its own code). */
const pendingSwitch = ref<string | null>(null)

// The code this device learns with now — shown so it can be saved (and before any switch).
const deviceCode = computed(() => session.resumeCode)

const canSubmit = computed(() => code.value.trim().length > 0 && !busy.value)

function isSameAsDevice(c: string): boolean {
  return !!deviceCode.value && normalizeResumeCode(c) === normalizeResumeCode(deviceCode.value)
}

// A shared link carries the code in `?code=`. It is taken out of the address bar right away (it is
// the learner's key), then: no code on this device → resume at once; a different one → ask first.
onMounted(() => {
  const q = route.query.code
  const incoming = (Array.isArray(q) ? q[0] : q)?.trim()
  if (!incoming) return
  void router.replace({ query: {} })
  code.value = formatResumeCode(incoming)
  void go()
})

/** Submit (form or link): same code → nothing to do; different code on a device that has one →
 *  confirm first; otherwise resume. */
async function go() {
  if (!canSubmit.value) return
  error.value = null
  const c = code.value.trim()
  if (isSameAsDevice(c)) {
    toast.info(t('resume.already_using'))
    void router.push({ name: 'home' })
    return
  }
  if (deviceCode.value) {
    pendingSwitch.value = formatResumeCode(c)
    return
  }
  await resume(c)
}

async function resume(c: string) {
  busy.value = true
  error.value = null
  try {
    await session.resumeWithCode(c)
    pendingSwitch.value = null
    void router.push({ name: 'home' })
  } catch (e) {
    pendingSwitch.value = null
    // An unknown code is "check it"; anything else (offline, server busy) says so in kind words.
    error.value = t(friendlyErrorKey(e, { not_found: 'resume.not_found', generic: 'resume.not_found' }))
  } finally {
    busy.value = false
  }
}

function confirmSwitch() {
  if (pendingSwitch.value && !busy.value) void resume(pendingSwitch.value)
}

function keepCurrent() {
  pendingSwitch.value = null
  void router.push({ name: 'home' })
}

async function copyDeviceCode() {
  if (!deviceCode.value) return
  try {
    await navigator.clipboard.writeText(deviceCode.value)
    toast.success(t('resume.copied'))
  } catch {
    toast.info(t('resume.copy_failed')) // the code is on screen to copy by hand
  }
}
</script>

<template>
  <section class="sa-resume">
    <h1 class="sa-resume__title">{{ t('resume.title') }}</h1>

    <!-- Switching learners on a device that already has one: show their code first, then ask. -->
    <div
      v-if="pendingSwitch && deviceCode"
      class="sa-card sa-resume__switch"
      role="alertdialog"
      aria-labelledby="resume-switch-title"
      aria-describedby="resume-switch-body"
    >
      <h2 id="resume-switch-title" class="sa-resume__switch-title">{{ t('resume.switch_title') }}</h2>
      <p id="resume-switch-body" class="sa-resume__switch-body">{{ t('resume.switch_body') }}</p>
      <p class="sa-resume__saved-label">{{ t('resume.device_code') }}</p>
      <p class="sa-resume__code">{{ deviceCode }}</p>
      <SaButton variant="ghost" size="sm" icon="check" @click="copyDeviceCode">
        {{ t('resume.copy') }}
      </SaButton>
      <p class="sa-resume__switch-new">{{ t('resume.switch_new', { code: pendingSwitch }) }}</p>
      <div class="sa-resume__switch-actions">
        <SaButton variant="primary" block :loading="busy" @click="confirmSwitch">
          {{ t('resume.switch_confirm') }}
        </SaButton>
        <SaButton variant="ghost" block :disabled="busy" @click="keepCurrent">
          {{ t('resume.switch_keep') }}
        </SaButton>
      </div>
    </div>

    <!-- This device's own code, to copy / write down. -->
    <div v-else-if="deviceCode" class="sa-card sa-resume__saved" role="status">
      <p class="sa-resume__saved-label">{{ t('resume.your_code') }}</p>
      <p class="sa-resume__code">{{ deviceCode }}</p>
      <SaButton variant="ghost" size="sm" icon="check" @click="copyDeviceCode">
        {{ t('resume.copy') }}
      </SaButton>
      <p class="sa-resume__saved-hint">{{ t('resume.save_hint') }}</p>
    </div>

    <form v-if="!pendingSwitch" class="sa-card sa-resume__form" @submit.prevent="go">
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
      <!-- The saved-code card above already shows this hint; only show it here in the plain entry case. -->
      <p v-if="!deviceCode" id="resume-hint" class="sa-resume__hint">{{ t('resume.save_hint') }}</p>
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
.sa-resume__switch {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  padding: 1.1rem;
  text-align: center;
  border: 2px solid var(--color-sun);
  background: color-mix(in srgb, var(--color-sun) 8%, var(--color-surface));
}
.sa-resume__switch-title {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 800;
}
.sa-resume__switch-body {
  margin: 0;
  max-width: 36ch;
}
.sa-resume__switch-new {
  margin: 0.25rem 0 0;
  font-weight: 700;
}
.sa-resume__switch-actions {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  width: 100%;
  margin-top: 0.25rem;
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
  min-width: var(--tap-min);
  justify-content: center;
  padding-inline: 0.75rem;
  display: inline-flex;
  align-items: center;
}
</style>

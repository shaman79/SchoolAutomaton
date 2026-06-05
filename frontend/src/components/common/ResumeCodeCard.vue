<script setup lang="ts">
/**
 * Shows the learner THEIR resume/continuation code (anonymous, no account) so they can save it and
 * continue on any device. Surfaced on Home and in Settings. Copy-to-clipboard with a toast.
 * Renders nothing if there's no code yet (a profile is created lazily on first prompt).
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import SaButton from './SaButton.vue'
import { toast } from './useToasts'
import { useSessionStore } from '@/stores/session'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const { t } = useI18n()
const session = useSessionStore()
const code = computed(() => session.resumeCode ?? '')

async function copy() {
  if (!code.value) return
  try {
    await navigator.clipboard.writeText(code.value)
    toast.success(t('resume.copied'))
  } catch {
    // Fallback for browsers/contexts without the async clipboard API.
    const ta = document.createElement('textarea')
    ta.value = code.value
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      toast.success(t('resume.copied'))
    } catch {
      toast.error(t('resume.copy_failed'))
    }
    ta.remove()
  }
}
</script>

<template>
  <section v-if="code" class="sa-code" :class="{ 'sa-code--compact': compact }" aria-labelledby="sa-code-title">
    <div class="sa-code__head">
      <span class="sa-code__key" aria-hidden="true">🔑</span>
      <h2 id="sa-code-title" class="sa-code__title">{{ t('resume.your_code') }}</h2>
    </div>
    <div class="sa-code__row">
      <code class="sa-code__value" aria-label="code.value">{{ code }}</code>
      <SaButton variant="ghost" size="sm" icon="check" @click="copy">{{ t('resume.copy') }}</SaButton>
    </div>
    <p v-if="!compact" class="sa-code__hint">{{ t('resume.save_hint') }}</p>
  </section>
</template>

<style scoped>
.sa-code {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.9rem 1rem;
  border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--color-sun) 14%, var(--color-surface));
  border: 1px solid color-mix(in srgb, var(--color-sun) 45%, var(--color-line));
}
.sa-code--compact {
  background: var(--color-surface-2);
  border-color: var(--color-line);
  padding: 0.75rem 0.85rem;
}
.sa-code__head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.sa-code__key {
  font-size: 1.2rem;
}
.sa-code__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}
.sa-code__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.sa-code__value {
  font-family: ui-monospace, 'Cascadia Code', 'Source Code Pro', monospace;
  font-size: clamp(1.25rem, 6vw, 1.6rem);
  font-weight: 800;
  letter-spacing: 0.12em;
  color: var(--color-ink);
  user-select: all;
}
.sa-code__hint {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.4;
  color: var(--color-ink-soft);
}
</style>

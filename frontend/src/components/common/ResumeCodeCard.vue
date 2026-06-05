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

// A shareable continue link with the code baked in — paste to a parent/another device and one tap
// resumes (ResumeView reads ?code= and auto-resumes). The code travels in the URL on purpose; it is
// the anonymous credential, the same thing the learner would otherwise type by hand.
const shareUrl = computed(() =>
  code.value
    ? `${window.location.origin}/resume?code=${encodeURIComponent(code.value)}`
    : '',
)

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Fallback for browsers/contexts without the async clipboard API.
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }
    ta.remove()
    return ok
  }
}

async function copy() {
  if (!code.value) return
  if (await writeClipboard(code.value)) toast.success(t('resume.copied'))
  else toast.error(t('resume.copy_failed'))
}

async function shareLink() {
  if (!shareUrl.value) return
  // Prefer the native share sheet (great on phones — straight to Messages/WhatsApp/email).
  const nav = navigator as Navigator & { share?: (d: ShareData) => Promise<void> }
  if (typeof nav.share === 'function') {
    try {
      await nav.share({ title: t('app.name'), text: t('resume.share_text'), url: shareUrl.value })
      return
    } catch {
      /* user dismissed or share unavailable → fall through to clipboard */
    }
  }
  if (await writeClipboard(shareUrl.value)) toast.success(t('resume.link_copied'))
  else toast.error(t('resume.copy_failed'))
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
      <span class="sa-code__actions">
        <SaButton variant="ghost" size="sm" icon="check" @click="copy">{{ t('resume.copy') }}</SaButton>
        <SaButton variant="ghost" size="sm" icon="share" @click="shareLink">{{ t('resume.share') }}</SaButton>
      </span>
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
/* Phones: code on top, two equal-width buttons below (space-between + wrap stranded them raggedly). */
.sa-code__row {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.6rem;
}
.sa-code__actions {
  display: flex;
  gap: 0.5rem;
}
.sa-code__actions > * {
  flex: 1;
}
@media (min-width: 40rem) {
  .sa-code__row {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
  .sa-code__actions {
    flex: 0 0 auto;
  }
  .sa-code__actions > * {
    flex: 0 0 auto;
  }
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

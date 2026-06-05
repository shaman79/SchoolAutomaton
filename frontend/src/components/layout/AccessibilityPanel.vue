<script setup lang="ts">
/**
 * Accessibility & preferences slide-over (modal dialog). Binds usePrefsStore
 * (theme / font / font_scale / reduced_motion / sound / locale) directly; every
 * change applies live to <html> (the store watches + applyToDom), switches the UI
 * locale via setLocale, and best-effort mirrors prefs to the server through
 * session.syncPrefs() (debounced so a slider drag isn't a request storm).
 *
 * Dialog a11y: role=dialog aria-modal, labelled heading, Esc to close, focus moved
 * in on open and restored on close, simple focus trap, scrim click closes. The
 * slide/scrim transitions are gated on the reduced-motion preference.
 */
import { useEventListener } from '@vueuse/core'
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import ResumeCodeCard from '@/components/common/ResumeCodeCard.vue'
import SaButton from '@/components/common/SaButton.vue'
import SaIcon from '@/components/common/SaIcon.vue'
import { useReducedMotion } from '@/composables/useReducedMotion'
import { FONT_OPTIONS, FONT_SCALE_STEPS, THEME_OPTIONS } from '@/composables/useTheme'
import { setLocale, SUPPORTED_LOCALES } from '@/i18n'
import { useSessionStore } from '@/stores/session'
import { usePrefsStore } from '@/stores/prefs'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { t } = useI18n()
const prefs = usePrefsStore()
const session = useSessionStore()
const { reduced } = useReducedMotion()

const panelRef = ref<HTMLElement | null>(null)
const closeBtnRef = ref<HTMLElement | null>(null)
let lastFocused: HTMLElement | null = null

const LOCALE_LABELS: Record<string, string> = { en: 'English', cs: 'Čeština' }

// --- live persistence: apply locally now, sync to server (debounced, best-effort) ---
let syncTimer: ReturnType<typeof setTimeout> | null = null
function scheduleSync() {
  if (syncTimer) clearTimeout(syncTimer)
  syncTimer = setTimeout(() => {
    session.syncPrefs().catch(() => {
      /* prefs are saved locally regardless; ignore offline / anon */
    })
  }, 500)
}

function onLocaleChange(loc: string) {
  prefs.locale = loc
  setLocale(loc)
  scheduleSync()
}

// Any pref change should be mirrored to the server.
watch(
  () => [prefs.theme, prefs.font, prefs.fontScale, prefs.reducedMotion, prefs.sound],
  scheduleSync,
)

function close() {
  emit('close')
}

// --- focus management + Esc + simple trap ---
useEventListener(document, 'keydown', (e: KeyboardEvent) => {
  if (!props.open) return
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  } else if (e.key === 'Tab') {
    const focusables = panelRef.value?.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])',
    )
    if (!focusables || focusables.length === 0) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    const activeEl = document.activeElement as HTMLElement | null
    if (e.shiftKey && activeEl === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && activeEl === last) {
      e.preventDefault()
      first.focus()
    }
  }
})

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      lastFocused = document.activeElement as HTMLElement | null
      document.body.style.overflow = 'hidden'
      await nextTick()
      closeBtnRef.value?.focus()
    } else {
      document.body.style.overflow = ''
      lastFocused?.focus?.()
    }
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition :name="reduced ? '' : 'sa-scrim'">
      <div
        v-if="open"
        class="fixed inset-0 z-50 bg-black/40"
        @click.self="close"
      >
        <Transition :name="reduced ? '' : 'sa-slide'" appear>
          <div
            ref="panelRef"
            class="sa-panel sa-card safe-top safe-bottom"
            role="dialog"
            aria-modal="true"
            :aria-label="t('a11y.settings')"
          >
            <header class="mb-4 flex items-center justify-between gap-3">
              <h2 class="flex items-center gap-2 text-xl font-bold">
                <SaIcon name="settings" :size="22" />
                {{ t('a11y.settings') }}
              </h2>
              <button
                ref="closeBtnRef"
                type="button"
                class="sa-tap grid place-items-center rounded-[var(--radius-pill)] text-[var(--color-ink-soft)] hover:bg-[var(--color-surface-2)]"
                :aria-label="t('common.close')"
                @click="close"
              >
                <SaIcon name="x" :size="22" />
              </button>
            </header>

            <div class="flex flex-col gap-6 overflow-y-auto pb-2">
              <!-- Your code to continue (anonymous; no account) -->
              <ResumeCodeCard v-if="session.resumeCode" />

              <!-- Language -->
              <fieldset class="flex flex-col gap-2">
                <legend class="mb-1 font-semibold">{{ t('a11y.language') }}</legend>
                <div class="flex flex-wrap gap-2">
                  <button
                    v-for="loc in SUPPORTED_LOCALES"
                    :key="loc"
                    type="button"
                    class="sa-opt"
                    :class="{ 'sa-opt--on': prefs.locale === loc }"
                    :aria-pressed="prefs.locale === loc"
                    @click="onLocaleChange(loc)"
                  >
                    {{ LOCALE_LABELS[loc] ?? loc }}
                  </button>
                </div>
              </fieldset>

              <!-- Theme -->
              <fieldset class="flex flex-col gap-2">
                <legend class="mb-1 font-semibold">{{ t('a11y.theme') }}</legend>
                <div class="flex flex-wrap gap-2">
                  <button
                    v-for="opt in THEME_OPTIONS"
                    :key="opt.value"
                    type="button"
                    class="sa-opt"
                    :class="{ 'sa-opt--on': prefs.theme === opt.value }"
                    :aria-pressed="prefs.theme === opt.value"
                    @click="prefs.theme = opt.value"
                  >
                    {{ t(opt.labelKey) }}
                  </button>
                </div>
              </fieldset>

              <!-- Font -->
              <fieldset class="flex flex-col gap-2">
                <legend class="mb-1 font-semibold">{{ t('a11y.font') }}</legend>
                <div class="flex flex-wrap gap-2">
                  <button
                    v-for="opt in FONT_OPTIONS"
                    :key="opt.value"
                    type="button"
                    class="sa-opt"
                    :class="{ 'sa-opt--on': prefs.font === opt.value }"
                    :aria-pressed="prefs.font === opt.value"
                    @click="prefs.font = opt.value"
                  >
                    {{ t(opt.labelKey) }}
                  </button>
                </div>
              </fieldset>

              <!-- Text size -->
              <div class="flex flex-col gap-2">
                <label for="a11y-scale" class="font-semibold">
                  {{ t('a11y.text_size') }}
                  <span class="ml-1 font-normal text-[var(--color-ink-soft)]"
                    >{{ Math.round(prefs.fontScale * 100) }}%</span
                  >
                </label>
                <input
                  id="a11y-scale"
                  type="range"
                  class="sa-range"
                  :min="0"
                  :max="FONT_SCALE_STEPS.length - 1"
                  :step="1"
                  :value="FONT_SCALE_STEPS.indexOf(prefs.fontScale as (typeof FONT_SCALE_STEPS)[number]) === -1 ? 1 : FONT_SCALE_STEPS.indexOf(prefs.fontScale as (typeof FONT_SCALE_STEPS)[number])"
                  :aria-valuetext="`${Math.round(prefs.fontScale * 100)}%`"
                  @input="prefs.fontScale = FONT_SCALE_STEPS[Number(($event.target as HTMLInputElement).value)]"
                />
              </div>

              <!-- Toggles -->
              <div class="flex flex-col gap-3">
                <label class="sa-toggle">
                  <span class="font-semibold">{{ t('a11y.reduced_motion') }}</span>
                  <input v-model="prefs.reducedMotion" type="checkbox" class="sa-switch" />
                </label>
                <label class="sa-toggle">
                  <span class="font-semibold">{{ t('a11y.sound') }}</span>
                  <input v-model="prefs.sound" type="checkbox" class="sa-switch" />
                </label>
              </div>

              <p class="text-xs text-[var(--color-ink-soft)]">{{ t('a11y.synced_hint') }}</p>
            </div>

            <footer class="mt-4">
              <SaButton variant="ghost" block icon="check" @click="close">
                {{ t('common.done') }}
              </SaButton>
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sa-panel {
  position: absolute;
  inset: 0 0 0 auto;
  width: min(26rem, 100%);
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-card) 0 0 var(--radius-card);
  padding: 1.1rem 1.1rem 0.5rem;
  overflow: hidden;
}
@media (max-width: 480px) {
  /* On phones the sheet rises from the bottom (thumb-reachable). */
  .sa-panel {
    inset: auto 0 0 0;
    width: 100%;
    max-height: 90dvh;
    border-radius: var(--radius-card) var(--radius-card) 0 0;
  }
}

.sa-opt {
  min-height: var(--tap-min);
  padding: 0.5rem 0.9rem;
  border-radius: var(--radius-btn);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  font-weight: 600;
  cursor: pointer;
}
.sa-opt--on {
  border-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 12%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  min-height: var(--tap-min);
  cursor: pointer;
}
.sa-switch {
  appearance: none;
  width: 3rem;
  height: 1.65rem;
  border-radius: var(--radius-pill);
  background: var(--color-line);
  position: relative;
  cursor: pointer;
  transition: background 0.15s ease;
  flex-shrink: 0;
}
.sa-switch::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 1.2rem;
  height: 1.2rem;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgb(0 0 0 / 0.3);
  transition: transform 0.15s ease;
}
.sa-switch:checked {
  background: var(--color-primary);
}
.sa-switch:checked::after {
  transform: translateX(1.35rem);
}
.sa-range {
  width: 100%;
  height: var(--tap-min);
  accent-color: var(--color-primary);
  cursor: pointer;
}
:root[data-reduced-motion='true'] .sa-switch,
:root[data-reduced-motion='true'] .sa-switch::after {
  transition: none;
}

/* transitions (skipped under reduced motion via empty name) */
.sa-scrim-enter-active,
.sa-scrim-leave-active {
  transition: opacity 0.2s ease;
}
.sa-scrim-enter-from,
.sa-scrim-leave-to {
  opacity: 0;
}
.sa-slide-enter-active,
.sa-slide-leave-active {
  transition: transform 0.24s cubic-bezier(0.22, 1, 0.36, 1);
}
.sa-slide-enter-from,
.sa-slide-leave-to {
  transform: translateX(100%);
}
@media (max-width: 480px) {
  .sa-slide-enter-from,
  .sa-slide-leave-to {
    transform: translateY(100%);
  }
}
</style>

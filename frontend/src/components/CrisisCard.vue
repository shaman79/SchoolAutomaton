<script setup lang="ts">
/**
 * Non-dismissable crisis-support card (SPEC §4 #8 + safety model). Shown when the sanitizer
 * returns a `crisis` Decision. It is intentionally NOT closeable: it surfaces localized help
 * resources (phone / SMS / link) and a clear AI-disclosure, and it never offers to "continue"
 * the original request. Conservative, supportive, color is NOT the only signal (icon + text).
 *
 * Placed under src/components/ (root) rather than common/ to avoid clashing with F1.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import SaIcon from '@/components/common/SaIcon.vue'
import type { CrisisResource } from '@/types/session'

const props = withDefaults(
  defineProps<{
    /** Localized supportive message from the sanitizer (untrusted -> rendered as plain text). */
    message?: string | null
    /** Localized AI-disclosure copy from the sanitizer. */
    disclosure?: string | null
    resources?: CrisisResource[]
  }>(),
  { message: null, disclosure: null, resources: () => [] },
)

const { t } = useI18n()

function telHref(phone: string): string {
  return `tel:${phone.replace(/[^+0-9]/g, '')}`
}
function smsHref(sms: string): string {
  return `sms:${sms.replace(/[^+0-9]/g, '')}`
}

const hasResources = computed(() => (props.resources?.length ?? 0) > 0)
</script>

<template>
  <!-- role=alert + aria-live=assertive: announced immediately to assistive tech. -->
  <section
    class="sa-crisis sa-card"
    role="alert"
    aria-live="assertive"
    :aria-label="t('crisis.title')"
  >
    <div class="sa-crisis__head">
      <span class="sa-crisis__icon" aria-hidden="true">
        <SaIcon name="hint" :size="26" />
      </span>
      <h2 class="sa-crisis__title">{{ t('crisis.title') }}</h2>
    </div>

    <p v-if="message" class="sa-crisis__message">{{ message }}</p>
    <p v-else class="sa-crisis__message">{{ t('crisis.default_message') }}</p>

    <ul v-if="hasResources" class="sa-crisis__list">
      <li v-for="(r, i) in resources" :key="`${r.name}-${i}`" class="sa-crisis__resource">
        <p class="sa-crisis__resource-name">{{ r.name }}</p>
        <p v-if="r.hours" class="sa-crisis__resource-hours">{{ r.hours }}</p>
        <div class="sa-crisis__actions">
          <a
            v-if="r.phone"
            :href="telHref(r.phone)"
            class="sa-btn sa-btn-primary"
          >
            {{ t('crisis.call') }} {{ r.phone }}
          </a>
          <a
            v-if="r.sms"
            :href="smsHref(r.sms)"
            class="sa-btn sa-btn-ghost"
          >
            {{ t('crisis.text') }} {{ r.sms }}
          </a>
          <a
            v-if="r.url"
            :href="r.url"
            target="_blank"
            rel="noopener noreferrer"
            class="sa-btn sa-btn-ghost"
          >
            {{ t('crisis.visit') }}
          </a>
        </div>
      </li>
    </ul>

    <p class="sa-crisis__disclosure">
      {{ disclosure || t('crisis.disclaimer') }}
    </p>

    <RouterLink to="/" class="sa-crisis__home">{{ t('common.back') }}</RouterLink>
  </section>
</template>

<style scoped>
.sa-crisis {
  /* Strong, calm border — color reinforces the icon+text, never the sole cue. */
  border: 2px solid var(--color-sky);
  background: color-mix(in srgb, var(--color-sky) 8%, var(--color-surface));
  padding: 1.1rem 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.sa-crisis__head {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.sa-crisis__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  flex: none;
  border-radius: var(--radius-pill);
  background: var(--color-sky);
  color: #04304a;
}
.sa-crisis__title {
  font-size: 1.2rem;
  font-weight: 800;
  margin: 0;
}
.sa-crisis__message {
  margin: 0;
  line-height: 1.6;
}
.sa-crisis__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.sa-crisis__resource {
  border: 1px solid var(--color-line);
  border-radius: var(--radius-btn);
  padding: 0.75rem 0.85rem;
  background: var(--color-surface);
}
.sa-crisis__resource-name {
  font-weight: 700;
  margin: 0;
}
.sa-crisis__resource-hours {
  margin: 0.1rem 0 0;
  font-size: 0.85rem;
  color: var(--color-ink-soft);
}
.sa-crisis__actions {
  margin-top: 0.6rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
/* On phones, make each action full-width and easy to tap. */
.sa-crisis__actions .sa-btn {
  flex: 1 1 100%;
}
@media (min-width: 480px) {
  .sa-crisis__actions .sa-btn {
    flex: 0 1 auto;
  }
}
.sa-crisis__disclosure {
  margin: 0;
  font-size: 0.85rem;
  color: var(--color-ink-soft);
  border-top: 1px dashed var(--color-line);
  padding-top: 0.75rem;
}
.sa-crisis__home {
  align-self: flex-start;
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
  min-height: var(--tap-min);
  display: inline-flex;
  align-items: center;
}
</style>

<script setup lang="ts">
/**
 * Compact, unobtrusive footer. Carries the AI-content disclosure (child-facing transparency) and the
 * way in for parents. (Entering a code lives on Home and in Settings; the admin sign-in is at
 * /admin/login — not a link children see on every page.) Mobile-first: stacks on phones, row on >=sm.
 */
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const year = new Date().getFullYear()
</script>

<template>
  <footer
    class="mt-8 border-t border-[var(--color-line)] safe-bottom"
    role="contentinfo"
  >
    <div
      class="mx-auto flex w-full max-w-screen-sm flex-col items-center gap-2 px-4 py-5 text-center text-xs text-[var(--color-ink-soft)] md:max-w-2xl lg:max-w-3xl sm:flex-row sm:justify-between sm:text-left"
    >
      <p>© {{ year }} {{ t('app.name') }} · {{ t('footer.ai_disclosure') }}</p>
      <nav class="flex flex-wrap items-center justify-center gap-x-2 sm:shrink-0 sm:flex-nowrap" :aria-label="t('footer.nav_label')">
        <RouterLink to="/parent" class="sa-tap inline-flex items-center justify-center px-2 underline hover:text-[var(--color-primary)]">
          {{ t('footer.parents') }}
        </RouterLink>
      </nav>
    </div>
  </footer>
</template>

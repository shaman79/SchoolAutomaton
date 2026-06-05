<script setup lang="ts">
/**
 * Compact, unobtrusive footer. Carries the AI-content disclosure (child-facing
 * transparency), a resume-code shortcut, and a discreet admin link. Mobile-first:
 * stacks on phones, row on >=sm.
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
      class="mx-auto flex w-full max-w-screen-sm flex-col items-center gap-2 px-4 py-5 text-center text-xs text-[var(--color-ink-soft)] lg:max-w-2xl sm:flex-row sm:justify-between sm:text-left"
    >
      <p>© {{ year }} {{ t('app.name') }} · {{ t('footer.ai_disclosure') }}</p>
      <nav class="flex items-center gap-4" :aria-label="t('footer.nav_label')">
        <RouterLink to="/resume" class="underline hover:text-[var(--color-primary)]">
          {{ t('resume.title') }}
        </RouterLink>
        <RouterLink to="/admin/login" class="underline hover:text-[var(--color-primary)]">
          {{ t('footer.admin') }}
        </RouterLink>
      </nav>
    </div>
  </footer>
</template>

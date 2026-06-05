<script setup lang="ts">
/* PLACEHOLDER — F4 agent replaces with the celebratory results screen: score, XP gain animation,
   streak, new badges, mastery changes, growth-mindset message. Reduced-motion aware. */
import { useI18n } from 'vue-i18n'

import { useTestStore } from '@/stores/test'

const { t } = useI18n()
const test = useTestStore()
</script>

<template>
  <section class="py-12 flex flex-col items-center gap-4 text-center">
    <h1 class="text-3xl font-extrabold">{{ t('results.title') }}</h1>
    <pre class="sa-card p-4 text-left text-xs overflow-auto w-full">{{ test.summary }}</pre>
    <router-link to="/" class="sa-btn sa-btn-primary">{{ t('results.again') }}</router-link>
  </section>
</template>

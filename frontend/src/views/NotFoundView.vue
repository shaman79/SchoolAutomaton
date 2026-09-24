<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import SaButton from '@/components/common/SaButton.vue'

const { t } = useI18n()
</script>

<template>
  <section class="py-20 flex flex-col items-center gap-4 text-center">
    <p class="text-6xl" aria-hidden="true">🧭</p>
    <h1 class="text-2xl font-bold">{{ t('not_found.title') }}</h1>
    <SaButton variant="primary" to="/" icon="home">{{ t('not_found.back') }}</SaButton>
  </section>
</template>

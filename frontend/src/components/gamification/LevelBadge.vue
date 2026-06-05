<script setup lang="ts">
/**
 * Round level medallion. The number is the meaning (never color-only): screen readers get
 * "Level N" via aria-label. Sizes scale the medallion but keep contrast and legibility.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(
  defineProps<{
    level: number
    size?: 'sm' | 'md' | 'lg'
  }>(),
  { size: 'md' },
)

const { t } = useI18n()

const dim = computed(() => ({ sm: '2.25rem', md: '3rem', lg: '4rem' })[props.size])
const fontSize = computed(() => ({ sm: '1rem', md: '1.3rem', lg: '1.7rem' })[props.size])
const label = computed(() => `${t('gamification.level')} ${props.level}`)
</script>

<template>
  <span
    class="sa-level-badge inline-grid shrink-0 place-items-center font-extrabold text-[var(--color-on-primary)]"
    :style="{ width: dim, height: dim, fontSize }"
    role="img"
    :aria-label="label"
  >
    <span aria-hidden="true">{{ level }}</span>
  </span>
</template>

<style scoped>
.sa-level-badge {
  border-radius: 999px;
  background: radial-gradient(120% 120% at 30% 20%, var(--color-accent), var(--color-primary) 55%, var(--color-primary-strong));
  box-shadow: var(--shadow-card);
  /* Inner ring for a crisp medallion edge that survives high-contrast theme. */
  outline: 2px solid color-mix(in srgb, var(--color-on-primary) 55%, transparent);
  outline-offset: -4px;
  line-height: 1;
}
:root[data-theme='highcontrast'] .sa-level-badge {
  background: var(--color-primary);
  outline-color: var(--color-on-primary);
}
</style>

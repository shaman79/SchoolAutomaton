<script setup lang="ts">
/**
 * "7 days | 30 days" for the parent overview — a native radio group styled as a segmented control,
 * so screen readers announce it as a choice and the arrow keys move between the options. Each option
 * is a full ≥44px target; the chosen one is marked by weight + a filled background + its radio
 * state, never by colour alone.
 */
import { useI18n } from 'vue-i18n'

import { SUMMARY_DAYS, type SummaryDays } from '@/stores/parent'

defineProps<{ modelValue: SummaryDays; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', days: SummaryDays): void }>()

const { t } = useI18n()
const name = `sa-period-${Math.random().toString(36).slice(2, 8)}`
</script>

<template>
  <fieldset class="sa-period" :disabled="disabled">
    <legend class="sr-only">{{ t('parents.period_label') }}</legend>
    <label v-for="days in SUMMARY_DAYS" :key="days" class="sa-period__option">
      <input
        type="radio"
        class="sa-period__input"
        :name="name"
        :value="days"
        :checked="modelValue === days"
        @change="emit('update:modelValue', days)"
      />
      <span class="sa-period__text">{{ t('parents.period_days', { n: days }) }}</span>
    </label>
  </fieldset>
</template>

<style scoped>
.sa-period {
  display: inline-flex;
  margin: 0;
  padding: 0.2rem;
  border: 2px solid var(--color-line);
  border-radius: var(--radius-pill);
  background: var(--color-surface-2);
}
.sa-period__option {
  position: relative;
  display: inline-flex;
}
/* Visually hidden but focusable — the label is the visible target. */
.sa-period__input {
  position: absolute;
  inset: 0;
  opacity: 0;
  margin: 0;
  cursor: pointer;
}
.sa-period__text {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--tap-min);
  min-width: 5.5rem;
  padding: 0 1rem;
  border-radius: var(--radius-pill);
  font-weight: 600;
  color: var(--color-ink-soft);
}
.sa-period__input:checked + .sa-period__text {
  background: var(--color-surface);
  color: var(--color-ink);
  font-weight: 800;
  box-shadow: 0 1px 3px rgb(0 0 0 / 0.12);
}
.sa-period__input:focus-visible + .sa-period__text {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
}
.sa-period:disabled {
  opacity: 0.7;
}
</style>

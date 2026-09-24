<script setup lang="ts">
/**
 * One-tap class picker ("Moje třída", in Settings). Big pill buttons grouped by school stage, named
 * the way the learner's own education system names them (lib/grades). Picking a class lets every
 * later prompt skip "for 4th grade" — the backend applies it whenever a prompt names no level —
 * which matters most for the youngest learners, who can barely type yet.
 *
 * Mobile-first: wrapping >=44px pills, a stage heading per group, aria-pressed on the current class.
 */
import { computed } from 'vue'

import { schoolYearGroups, schoolYearLabel } from '@/lib/grades'

const props = defineProps<{
  modelValue: number | null
  educationLocale: string | null
  /** When given, a first pill lets the learner clear the class (emits null). */
  unsetLabel?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', year: number | null): void }>()

const groups = computed(() => schoolYearGroups(props.educationLocale))
</script>

<template>
  <div class="sa-grades">
    <div v-if="unsetLabel" class="sa-grades__pills">
      <button
        type="button"
        class="sa-grades__pill"
        :class="{ 'sa-grades__pill--on': modelValue === null }"
        :aria-pressed="modelValue === null"
        @click="emit('update:modelValue', null)"
      >
        {{ unsetLabel }}
      </button>
    </div>
    <div v-for="g in groups" :key="g.label" class="sa-grades__group" role="group" :aria-label="g.label">
      <p class="sa-grades__stage" aria-hidden="true">{{ g.label }}</p>
      <div class="sa-grades__pills">
        <button
          v-for="y in g.years"
          :key="y"
          type="button"
          class="sa-grades__pill"
          :class="{ 'sa-grades__pill--on': modelValue === y }"
          :aria-pressed="modelValue === y"
          @click="emit('update:modelValue', y)"
        >
          {{ schoolYearLabel(y, educationLocale) }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sa-grades {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.sa-grades__stage {
  margin: 0 0 0.35rem;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--color-ink-soft);
}
.sa-grades__pills {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.sa-grades__pill {
  min-height: var(--tap-min);
  padding: 0.45rem 0.9rem;
  border-radius: var(--radius-pill);
  border: 2px solid var(--color-line);
  background: var(--color-surface-2);
  font: inherit;
  font-weight: 700;
  color: var(--color-ink);
  cursor: pointer;
  transition: border-color 0.12s ease, transform 0.12s ease;
}
@media (hover: hover) {
  .sa-grades__pill:hover {
    border-color: var(--color-primary);
    transform: translateY(-1px);
  }
}
/* Selected: border + tint + a check mark, so the state never relies on color alone. */
.sa-grades__pill--on {
  border-color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 14%, var(--color-surface));
  color: var(--color-primary-strong);
}
.sa-grades__pill--on::before {
  content: '✓ ';
}
:root[data-reduced-motion='true'] .sa-grades__pill {
  transition: none;
}
</style>

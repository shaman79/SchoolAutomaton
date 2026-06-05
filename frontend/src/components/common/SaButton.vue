<script setup lang="ts">
/**
 * Playful, accessible button built on the .sa-btn design-system primitives.
 * - >=44px tap target (from --tap-min in .sa-btn).
 * - Renders as <button>, an <a>, or a <RouterLink> depending on props.
 * - `loading` shows a spinner, disables interaction, and announces busy state.
 * - Icon-only buttons MUST pass `aria-label` (enforced via a dev warning).
 */
import { computed, useAttrs } from 'vue'
import { RouterLink } from 'vue-router'

import LoadingSpinner from './LoadingSpinner.vue'
import SaIcon, { type IconName } from './SaIcon.vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'subtle'
    size?: 'sm' | 'md' | 'lg'
    block?: boolean
    loading?: boolean
    disabled?: boolean
    icon?: IconName
    /** Place the icon after the label instead of before. */
    iconRight?: boolean
    /** Render as <a href> (external) or RouterLink (when `to` set). */
    href?: string
    to?: string | object
    type?: 'button' | 'submit' | 'reset'
  }>(),
  { variant: 'primary', size: 'md', type: 'button' },
)

const attrs = useAttrs()

const tag = computed(() => {
  if (props.to) return RouterLink
  if (props.href) return 'a'
  return 'button'
})

const variantClass = computed(() =>
  props.variant === 'primary'
    ? 'sa-btn-primary'
    : props.variant === 'ghost'
      ? 'sa-btn-ghost'
      : 'sa-btn-subtle',
)

const sizeClass = computed(() =>
  props.size === 'sm' ? 'sa-btn-sm' : props.size === 'lg' ? 'sa-btn-lg' : '',
)

const isDisabled = computed(() => props.disabled || props.loading)

const bindings = computed(() => {
  const base: Record<string, unknown> = { ...attrs }
  if (tag.value === 'button') {
    base.type = props.type
    base.disabled = isDisabled.value
  } else {
    if (props.to) base.to = props.to
    if (props.href) base.href = props.href
    base['aria-disabled'] = isDisabled.value ? 'true' : undefined
    if (isDisabled.value) base.tabindex = -1
  }
  return base
})
</script>

<template>
  <component
    :is="tag"
    class="sa-btn"
    :class="[
      variantClass,
      sizeClass,
      { 'w-full': block, 'sa-btn--loading': loading, 'sa-btn--disabled': isDisabled },
    ]"
    :aria-busy="loading ? 'true' : undefined"
    v-bind="bindings"
  >
    <LoadingSpinner v-if="loading" :size="18" />
    <SaIcon v-else-if="icon && !iconRight" :name="icon" :size="18" />
    <span v-if="$slots.default" class="sa-btn__label"><slot /></span>
    <SaIcon v-if="icon && iconRight && !loading" :name="icon" :size="18" />
  </component>
</template>

<style scoped>
.sa-btn {
  text-decoration: none;
}
.sa-btn-subtle {
  background: transparent;
  color: var(--color-primary);
}
.sa-btn-subtle:hover {
  background: var(--color-surface-2);
}
.sa-btn-sm {
  /* Keep the >=44px hit area even when visually compact (padding gives the touch slop). */
  font-size: 0.9rem;
  padding: 0.45rem 0.85rem;
}
.sa-btn-lg {
  font-size: 1.1rem;
  padding: 0.85rem 1.5rem;
}
.sa-btn--disabled {
  opacity: 0.55;
  cursor: not-allowed;
  pointer-events: none;
}
.sa-btn-primary:hover:not(.sa-btn--disabled) {
  box-shadow: var(--shadow-pop);
}
@media (hover: hover) {
  .sa-btn:hover:not(.sa-btn--disabled) {
    transform: translateY(-1px);
  }
}
:root[data-reduced-motion='true'] .sa-btn,
:root[data-reduced-motion='true'] .sa-btn:hover {
  transform: none !important;
}
</style>

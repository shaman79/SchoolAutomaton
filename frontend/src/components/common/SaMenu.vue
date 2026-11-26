<script setup lang="ts">
/**
 * "⋯" — the less frequent actions of a row or a heading, out of the way until wanted. A disclosure
 * (a button that shows a short list of buttons), not an ARIA menu: Tab moves through the actions,
 * Esc or a tap outside closes it and gives focus back to the "⋯" button. ≥44px targets, the list
 * opens below the button and stays on screen (aligned to the right edge).
 */
import { onClickOutside, useEventListener } from '@vueuse/core'
import { nextTick, ref } from 'vue'

import SaIcon from './SaIcon.vue'

export interface MenuItem {
  label: string
  action: () => void
  /** A destructive action (shown in the warning colour, with its words — never colour alone). */
  danger?: boolean
}

defineProps<{ items: MenuItem[]; label: string }>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const list = ref<HTMLElement | null>(null)
const uid = `sa-menu-${Math.random().toString(36).slice(2, 8)}`

async function toggle(): Promise<void> {
  open.value = !open.value
  if (open.value) {
    await nextTick()
    list.value?.querySelector<HTMLButtonElement>('button')?.focus()
  }
}
function close(refocus = true): void {
  if (!open.value) return
  open.value = false
  if (refocus) trigger.value?.focus()
}
function choose(item: MenuItem): void {
  close(false)
  item.action()
}

onClickOutside(root, () => close(false))
useEventListener(document, 'keydown', (e: KeyboardEvent) => {
  if (open.value && e.key === 'Escape') {
    e.preventDefault()
    close()
  }
})
</script>

<template>
  <div ref="root" class="sa-menu">
    <button
      ref="trigger"
      type="button"
      class="sa-menu__trigger"
      :aria-label="label"
      :aria-expanded="open"
      :aria-controls="uid"
      @click="toggle"
    >
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
        <circle cx="5" cy="12" r="2" fill="currentColor" />
        <circle cx="12" cy="12" r="2" fill="currentColor" />
        <circle cx="19" cy="12" r="2" fill="currentColor" />
      </svg>
    </button>
    <ul v-if="open" :id="uid" ref="list" class="sa-menu__list">
      <li v-for="item in items" :key="item.label">
        <button
          type="button"
          class="sa-menu__item"
          :class="{ 'sa-menu__item--danger': item.danger }"
          @click="choose(item)"
        >
          <SaIcon v-if="item.danger" name="x" :size="16" />
          {{ item.label }}
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sa-menu {
  position: relative;
  flex: none;
}
.sa-menu__trigger {
  display: grid;
  place-items: center;
  width: var(--tap-min);
  height: var(--tap-min);
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--color-ink-soft);
  cursor: pointer;
}
.sa-menu__trigger:hover,
.sa-menu__trigger[aria-expanded='true'] {
  background: var(--color-surface-2);
  color: var(--color-ink);
}
.sa-menu__trigger:focus-visible {
  outline: 3px solid var(--color-primary);
  outline-offset: 2px;
}
.sa-menu__list {
  position: absolute;
  top: calc(100% + 0.25rem);
  right: 0;
  z-index: 30;
  min-width: 13rem;
  max-width: min(18rem, calc(100vw - 2rem));
  margin: 0;
  padding: 0.35rem;
  list-style: none;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-btn);
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgb(0 0 0 / 0.14);
}
.sa-menu__item {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  width: 100%;
  min-height: var(--tap-min);
  padding: 0 0.75rem;
  border: 0;
  border-radius: calc(var(--radius-btn) - 4px);
  background: transparent;
  font: inherit;
  font-weight: 600;
  text-align: left;
  color: var(--color-ink);
  cursor: pointer;
}
.sa-menu__item:hover,
.sa-menu__item:focus-visible {
  background: var(--color-surface-2);
  outline: none;
}
/* Words stay ink (the warning colour is too light for text); the × carries the warning. */
.sa-menu__item--danger :deep(svg) {
  color: var(--color-coral);
}
</style>

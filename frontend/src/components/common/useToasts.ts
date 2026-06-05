/**
 * Lightweight, store-free toast queue shared by ToastHost. Any component can call
 * `toast.success(...)` / `toast.error(...)` etc. ToastHost renders the queue inside
 * an aria-live=polite region (assertive for errors). Kept tiny and dependency-free
 * so it lives alongside the design-system primitives (F1).
 */
import { reactive, readonly } from 'vue'

import type { IconName } from './SaIcon.vue'

export type ToastTone = 'info' | 'success' | 'warning' | 'error'

export interface Toast {
  id: number
  message: string
  tone: ToastTone
  icon?: IconName
  /** ms before auto-dismiss; 0 = sticky (manual dismiss only). */
  timeout: number
}

interface ToastOptions {
  tone?: ToastTone
  icon?: IconName
  timeout?: number
}

const state = reactive<{ items: Toast[] }>({ items: [] })
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let seq = 0

const DEFAULT_ICON: Record<ToastTone, IconName> = {
  info: 'sparkle',
  success: 'check',
  warning: 'hint',
  error: 'x',
}

function dismiss(id: number): void {
  const t = timers.get(id)
  if (t) {
    clearTimeout(t)
    timers.delete(id)
  }
  const idx = state.items.findIndex((x) => x.id === id)
  if (idx !== -1) state.items.splice(idx, 1)
}

function push(message: string, opts: ToastOptions = {}): number {
  const tone = opts.tone ?? 'info'
  const id = ++seq
  const timeout = opts.timeout ?? (tone === 'error' ? 6000 : 4000)
  state.items.push({ id, message, tone, icon: opts.icon ?? DEFAULT_ICON[tone], timeout })
  if (timeout > 0) timers.set(id, setTimeout(() => dismiss(id), timeout))
  return id
}

export const toasts = readonly(state)

export const toast = {
  show: push,
  info: (m: string, o?: ToastOptions) => push(m, { ...o, tone: 'info' }),
  success: (m: string, o?: ToastOptions) => push(m, { ...o, tone: 'success' }),
  warning: (m: string, o?: ToastOptions) => push(m, { ...o, tone: 'warning' }),
  error: (m: string, o?: ToastOptions) => push(m, { ...o, tone: 'error' }),
  dismiss,
}

<script setup lang="ts">
/**
 * Admin → Settings: one setting an admin can change (an AI model, the daily budget).
 *
 * Shows the value in effect, where it comes from (app default / the server's .env / changed here /
 * built in) and — for an admin who may edit — a control + Save, and Undo for a change made here.
 * A model change asks for an inline confirmation first: it switches every new lesson, quiz and
 * answer check at once. On a failure the input stays as typed and the error shows on this row.
 *
 * Emits `updated` with the ConfigItem the server returns, `unauthorized` on a 401/403.
 */
import { computed, nextTick, ref, watch } from 'vue'

import { toast } from '@/components/common/useToasts'
import { ApiError, api } from '@/lib/api'

import { isUnauthorized, type ConfigItem } from './adminApi'
import { useConfigFormat } from './useConfigFormat'

const props = defineProps<{ item: ConfigItem; token: string; canEdit: boolean }>()
const emit = defineEmits<{ updated: [item: ConfigItem]; unauthorized: [] }>()

const { t, label, help, formatValue, sourceLine, baseSourceWord } = useConfigFormat()
const P = 'admin.settings'

const ids = computed(() => {
  const base = `cfg-${props.item.key}`
  return {
    input: `${base}-input`,
    help: `${base}-help`,
    source: `${base}-source`,
    note: `${base}-note`,
    error: `${base}-error`,
    confirmTitle: `${base}-confirm-title`,
    confirmText: `${base}-confirm-text`,
  }
})

const isChoice = computed(() => props.item.kind === 'choice')
const isNumber = computed(() => props.item.kind === 'number' || props.item.kind === 'integer')
/** Changing a model switches every new lesson/quiz/answer check: confirm first. */
const needsConfirm = computed(() => props.item.group === 'models')
const editing = computed(() => props.canEdit && props.item.editable)

const rowLabel = computed(() => label(props.item.key))
const rowHelp = computed(() => help(props.item.key))
const valueText = computed(() => formatValue(props.item, props.item.value))
const valueInChoices = computed(
  () => !isChoice.value || props.item.choices.includes(String(props.item.value ?? '')),
)
/** The server's .env pins a value other than the app's own default (e.g. an older model). */
const envPinned = computed(
  () =>
    props.item.editable &&
    props.item.source === 'env' &&
    props.item.default_value !== null &&
    props.item.value !== props.item.default_value,
)

function initialDraft(): string {
  const v = props.item.value
  return typeof v === 'number' || typeof v === 'string' ? String(v) : ''
}

// Numbers are typed into a text field (inputmode decimal): a type="number" field silently drops a
// typed comma, so "12,5" became 125. Parsed below, accepting a comma or a dot.
const draft = ref<string>(initialDraft())
/** What waits for the inline confirmation (model rows): a save or an undo — both switch every learner. */
const pending = ref<'save' | 'undo' | null>(null)
const confirming = computed(() => pending.value !== null)
const busy = ref(false)
const error = ref<string | null>(null)
const confirmBtn = ref<HTMLButtonElement | null>(null)
const inputEl = ref<HTMLInputElement | HTMLSelectElement | null>(null)

// A new value from the server (after a save / undo here) resets the control. Separate sources, not
// one getter returning a fresh array (that fires on every reload and wiped what the admin had typed
// in OTHER rows whenever the whole config reloaded).
watch(
  [() => props.item.value, () => props.item.source, () => props.item.updated_at],
  () => {
    draft.value = initialDraft()
    pending.value = null
    error.value = null
  },
)
// Picking another value while the confirmation is open withdraws it.
watch(draft, () => {
  pending.value = null
})

const DECIMAL = /^\d+(?:\.\d+)?$/
const INTEGER = /^\d+$/
const normalized = computed(() => draft.value.trim().replace(',', '.'))
const draftNumber = computed(() => {
  const s = normalized.value
  return (props.item.kind === 'integer' ? INTEGER : DECIMAL).test(s) ? Number(s) : NaN
})
const changed = computed(() => {
  if (draft.value.trim() === '') return false
  if (isNumber.value) return draftNumber.value !== props.item.value
  return draft.value !== props.item.value
})

const describedBy = computed(() =>
  [rowHelp.value ? ids.value.help : null, ids.value.source, envPinned.value ? ids.value.note : null, error.value ? ids.value.error : null]
    .filter(Boolean)
    .join(' '),
)

const undoText = computed(() =>
  t(`${P}.undo`, {
    value: formatValue(props.item, props.item.base_value),
    source: baseSourceWord(props.item.base_source),
  }),
)

function rangeError(): string | null {
  const v = draftNumber.value
  const { min, max } = props.item
  // The server keeps cents: more decimals would be rounded — 0.004 to 0, which turns the cap off.
  if (props.item.kind === 'number' && /\.\d{3,}$/.test(normalized.value)) return t(`${P}.too_many_decimals`)
  const ok = Number.isFinite(v) && (min === null || v >= min) && (max === null || v <= max)
  if (ok) return null
  return t(`${P}.invalid_number`, {
    min: formatValue(props.item, min ?? 0),
    max: max === null ? '∞' : formatValue(props.item, max),
  })
}

function valueToSend(): string | number {
  return isNumber.value ? draftNumber.value : draft.value
}

async function askConfirm(action: 'save' | 'undo') {
  pending.value = action
  await nextTick()
  confirmBtn.value?.focus()
}

async function onSave() {
  if (!changed.value || busy.value) return
  error.value = null
  if (isNumber.value) {
    const problem = rangeError()
    if (problem) {
      error.value = problem
      return
    }
  }
  if (needsConfirm.value) {
    await askConfirm('save')
    return
  }
  await send()
}

async function onUndo() {
  if (busy.value) return
  error.value = null
  if (needsConfirm.value) {
    await askConfirm('undo')
    return
  }
  await undo()
}

function onConfirm() {
  if (pending.value === 'undo') void undo()
  else void send()
}

function cancelConfirm() {
  pending.value = null
  nextTick(() => inputEl.value?.focus())
}

/** After a save / undo the confirmation (or the Undo button) is gone and the field was disabled: put
 *  keyboard focus back on the field instead of letting it drop to the page start. */
async function refocus() {
  await nextTick()
  inputEl.value?.focus()
}

function failure(e: unknown): void {
  // The account lost the right to edit while signed in: not an expired session.
  if (e instanceof ApiError && e.status === 403 && e.detail === 'Read-only role') {
    error.value = t(`${P}.error_read_only`)
    return
  }
  if (isUnauthorized(e)) {
    emit('unauthorized')
    return
  }
  if (e instanceof ApiError) {
    if (e.status === 422) {
      // The server's own explanation (e.g. "daily_budget_usd must be between 0 and 1000").
      error.value = typeof e.detail === 'string' && e.detail.trim() ? e.detail : t(`${P}.error_invalid`)
      return
    }
    if (e.status === 400) {
      error.value = t(`${P}.error_not_editable`)
      return
    }
    if (e.status === 404) {
      error.value = t(`${P}.error_unknown`)
      return
    }
  }
  error.value = t(`${P}.error_save`)
}

async function send() {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    const updated = (await api.adminSetConfig(props.token, props.item.key, valueToSend())) as ConfigItem
    pending.value = null
    toast.success(t(`${P}.saved`, { label: rowLabel.value, value: formatValue(updated, updated.value) }))
    emit('updated', updated)
  } catch (e) {
    pending.value = null
    failure(e)
  } finally {
    busy.value = false
    void refocus()
  }
}

async function undo() {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    const updated = (await api.adminResetConfig(props.token, props.item.key)) as ConfigItem
    pending.value = null
    toast.success(t(`${P}.undone`, { label: rowLabel.value, value: formatValue(updated, updated.value) }))
    emit('updated', updated)
  } catch (e) {
    pending.value = null
    failure(e)
  } finally {
    busy.value = false
    void refocus()
  }
}

const fieldClass =
  'min-h-[var(--tap-min)] w-full min-w-0 rounded-[var(--radius-btn)] border border-[var(--color-line)] bg-[var(--color-surface-2)] px-3 sm:flex-1'
</script>

<template>
  <div class="flex flex-col gap-2" :aria-busy="busy ? 'true' : undefined" :data-key="item.key">
    <div>
      <h3 class="text-base font-bold">
        <label v-if="editing" :for="ids.input">{{ rowLabel }}</label>
        <template v-else>{{ rowLabel }}</template>
      </h3>
      <p v-if="rowHelp" :id="ids.help" class="text-sm text-[var(--color-ink-soft)]">{{ rowHelp }}</p>
    </div>

    <p class="flex flex-wrap items-baseline gap-x-1.5">
      <span class="text-sm text-[var(--color-ink-soft)]">{{ t('admin.settings.in_effect') }}</span>
      <strong class="font-bold [overflow-wrap:anywhere]" data-test="value">{{ valueText }}</strong>
    </p>
    <p :id="ids.source" class="text-sm text-[var(--color-ink-soft)]" data-test="source">{{ sourceLine(item) }}</p>

    <p
      v-if="envPinned"
      :id="ids.note"
      class="flex items-start gap-2 rounded-[var(--radius-btn)] p-3 text-sm"
      style="background: var(--color-bg-tint)"
      data-test="env-note"
    >
      <span aria-hidden="true" class="font-bold text-[var(--color-primary)]">i</span>
      <span>
        {{
          t(editing ? 'admin.settings.env_pinned' : 'admin.settings.env_pinned_view', {
            value: formatValue(item, item.value),
            default: formatValue(item, item.default_value),
          })
        }}
      </span>
    </p>

    <template v-if="editing">
      <div class="mt-1 flex flex-col gap-2 sm:flex-row sm:items-center">
        <select
          v-if="isChoice"
          :id="ids.input"
          ref="inputEl"
          v-model="draft"
          :class="fieldClass"
          :disabled="busy"
          :aria-describedby="describedBy"
        >
          <option v-if="!valueInChoices" :value="item.value" disabled>
            {{ t('admin.settings.unlisted', { value: String(item.value) }) }}
          </option>
          <option v-for="c in item.choices" :key="c" :value="c">
            {{ c === item.default_value ? t('admin.settings.recommended', { value: c }) : c }}
          </option>
        </select>
        <input
          v-else-if="isNumber"
          :id="ids.input"
          ref="inputEl"
          v-model="draft"
          type="text"
          :inputmode="item.kind === 'integer' ? 'numeric' : 'decimal'"
          autocomplete="off"
          :class="fieldClass"
          :disabled="busy"
          :aria-invalid="error ? 'true' : undefined"
          :aria-describedby="describedBy"
          @keydown.enter.prevent="onSave"
        />
        <input
          v-else
          :id="ids.input"
          ref="inputEl"
          v-model="draft"
          type="text"
          :class="fieldClass"
          :disabled="busy"
          :aria-invalid="error ? 'true' : undefined"
          :aria-describedby="describedBy"
          @keydown.enter.prevent="onSave"
        />
        <button
          type="button"
          class="sa-btn sa-btn-primary w-full disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          :disabled="!changed || busy || confirming"
          data-test="save"
          @click="onSave"
        >
          {{ t('admin.settings.save') }}
        </button>
      </div>

      <div
        v-if="confirming"
        role="group"
        :aria-labelledby="ids.confirmTitle"
        class="flex flex-col gap-3 rounded-[var(--radius-btn)] border-2 border-[var(--color-primary)] p-3"
        data-test="confirm"
        @keydown.esc="cancelConfirm"
      >
        <p :id="ids.confirmTitle" class="font-bold [overflow-wrap:anywhere]">
          {{
            pending === 'undo'
              ? t('admin.settings.confirm_undo_title', { value: formatValue(item, item.base_value) })
              : t('admin.settings.confirm_title', { value: String(draft) })
          }}
        </p>
        <p :id="ids.confirmText" class="text-sm">{{ t('admin.settings.confirm_model') }}</p>
        <div class="flex flex-col gap-2 sm:flex-row">
          <button
            ref="confirmBtn"
            type="button"
            class="sa-btn sa-btn-primary w-full disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
            :aria-describedby="ids.confirmText"
            :disabled="busy"
            data-test="confirm-yes"
            @click="onConfirm"
          >
            {{ t('admin.settings.confirm') }}
          </button>
          <button
            type="button"
            class="sa-btn sa-btn-ghost w-full disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
            :disabled="busy"
            data-test="confirm-no"
            @click="cancelConfirm"
          >
            {{ t('admin.settings.cancel') }}
          </button>
        </div>
      </div>

      <p
        v-if="error"
        :id="ids.error"
        role="alert"
        class="flex items-start gap-2 rounded-[var(--radius-btn)] border-l-4 border-[var(--color-coral)] p-3 text-sm"
        style="background: var(--color-surface-2)"
        data-test="error"
      >
        <span
          aria-hidden="true"
          class="inline-grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs font-bold text-[var(--color-on-coral)]"
          style="background: var(--color-coral)"
        >!</span>
        <span class="[overflow-wrap:anywhere]">{{ error }}</span>
      </p>

      <button
        v-if="item.source === 'admin'"
        type="button"
        class="sa-btn sa-btn-ghost w-full text-left disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:self-start"
        :disabled="busy"
        data-test="undo"
        @click="onUndo"
      >
        <span class="[overflow-wrap:anywhere]">{{ undoText }}</span>
      </button>
    </template>
  </div>
</template>

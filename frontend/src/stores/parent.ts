/** The children a parent follows FROM THIS DEVICE, by their parent codes (see /parent).
 *
 *  Kept only here (localStorage), like a learner's resume code: the server knows no parent identity.
 *  The name a parent gives a child is stored only on this device too — it never reaches the server,
 *  so the app stays anonymous. A code that stops working (a new one was made on the child's device,
 *  or sharing was stopped) is kept, flagged `revoked`, until the parent removes it or adds the new one.
 *
 *  Independent of the learner on this device (session store): forgetting or switching the learner
 *  leaves the followed children alone. */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/lib/api'
import { formatParentCode, normalizeCode } from '@/lib/codes'

export interface FollowedChild {
  /** Local id (routes/keys) — never sent anywhere. */
  id: string
  /** The parent code, formatted (`ABCDE-FGHJK`). */
  code: string
  /** What the parent calls the child — on this device only; '' = not named yet. */
  name: string
  addedAt: string
  /** The code no longer works (replaced / sharing stopped on the child's device). */
  revoked?: boolean
}

export type SummaryDays = 7 | 30
export const SUMMARY_DAYS: readonly SummaryDays[] = [7, 30]

/** A name is a label on this device, not an identity: short and plain. */
export const MAX_CHILD_NAME = 30

function localId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

export const useParentStore = defineStore(
  'parent',
  () => {
    const children = ref<FollowedChild[]>([])
    const selectedId = ref<string | null>(null)
    /** The overview period, shared by both overviews (the child's device and this one). */
    const period = ref<SummaryDays>(7)

    const selected = computed<FollowedChild | null>(
      () => children.value.find((c) => c.id === selectedId.value) ?? children.value[0] ?? null,
    )

    function findByCode(code: string): FollowedChild | undefined {
      const n = normalizeCode(code)
      return children.value.find((c) => normalizeCode(c.code) === n)
    }

    /** Follow a child by their parent code. Checks it with the server first (rejects with the
     *  ApiError — 401 for a code that doesn't work). A code already followed just gets selected
     *  (and is no longer flagged revoked — it worked). */
    async function add(rawCode: string): Promise<{ child: FollowedChild; existing: boolean }> {
      const code = formatParentCode(rawCode)
      await api.parentChild(code)
      const known = findByCode(code)
      if (known) {
        known.revoked = false
        selectedId.value = known.id
        return { child: known, existing: true }
      }
      const child: FollowedChild = { id: localId(), code, name: '', addedAt: new Date().toISOString() }
      children.value.push(child)
      selectedId.value = child.id
      return { child, existing: false }
    }

    function select(id: string): void {
      if (children.value.some((c) => c.id === id)) selectedId.value = id
    }

    function rename(id: string, name: string): void {
      const child = children.value.find((c) => c.id === id)
      if (child) child.name = name.trim().slice(0, MAX_CHILD_NAME)
    }

    function setRevoked(id: string, revoked: boolean): void {
      const child = children.value.find((c) => c.id === id)
      if (child && Boolean(child.revoked) !== revoked) child.revoked = revoked
    }

    function remove(id: string): void {
      children.value = children.value.filter((c) => c.id !== id)
      if (selectedId.value === id) selectedId.value = children.value[0]?.id ?? null
    }

    function setPeriod(days: number): void {
      if ((SUMMARY_DAYS as readonly number[]).includes(days)) period.value = days as SummaryDays
    }

    return { children, selectedId, period, selected, findByCode, add, select, rename, setRevoked, remove, setPeriod }
  },
  { persist: { pick: ['children', 'selectedId', 'period'] } },
)

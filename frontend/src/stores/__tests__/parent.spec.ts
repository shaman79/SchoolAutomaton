/**
 * The children a parent follows from this device: added only once the server accepts the code,
 * never twice (however the code is typed), named only here, and a code that stopped working is
 * kept (flagged) until it is replaced or removed.
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { parentChild: vi.fn() } }
})

import { ApiError, api } from '@/lib/api'
import { codeKind, formatParentCode, normalizeCode } from '@/lib/codes'
import { MAX_CHILD_NAME, useParentStore } from '@/stores/parent'

const parentChild = (api as unknown as Record<string, Mock>).parentChild

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  parentChild.mockResolvedValue({ school_year: 3, education_locale: 'cs-CZ' })
})

describe('codes', () => {
  it('tells a parent code from a resume code by its length', () => {
    expect(codeKind('K7QF-2M9X')).toBe('resume')
    expect(codeKind('abcde fghjk')).toBe('parent')
    expect(codeKind('ABCDE-FG')).toBe('unknown')
    expect(codeKind('ŽŽŽŽŽ-ŽŽŽŽŽ')).toBe('unknown')
    expect(formatParentCode('abcdefghjk')).toBe('ABCDE-FGHJK')
    expect(normalizeCode('o1l-iu')).toBe('0111V')
  })
})

describe('useParentStore', () => {
  it('adds a child only once the server accepts the code, and selects it', async () => {
    const store = useParentStore()
    const { child, existing } = await store.add('abcde fghjk')
    expect(parentChild).toHaveBeenCalledWith('ABCDE-FGHJK')
    expect(existing).toBe(false)
    expect(child).toMatchObject({ code: 'ABCDE-FGHJK', name: '' })
    expect(store.selected?.id).toBe(child.id)

    parentChild.mockRejectedValueOnce(new ApiError(401, 'Unknown parent code'))
    await expect(store.add('ZZZZZ-ZZZZZ')).rejects.toMatchObject({ status: 401 })
    expect(store.children).toHaveLength(1)
  })

  it('never follows the same child twice, however the code is typed', async () => {
    const store = useParentStore()
    const first = (await store.add('ABCDE-FGHJK')).child
    const again = await store.add('abcdefghjk')
    expect(again).toMatchObject({ existing: true })
    expect(again.child.id).toBe(first.id)
    expect(store.children).toHaveLength(1)
  })

  it('a code that works again is no longer flagged', async () => {
    const store = useParentStore()
    const { child } = await store.add('ABCDE-FGHJK')
    store.setRevoked(child.id, true)
    expect(store.selected?.revoked).toBe(true)
    await store.add('ABCDE-FGHJK')
    expect(store.selected?.revoked).toBe(false)
  })

  it('names stay short and plain; removing selects the next child', async () => {
    const store = useParentStore()
    const a = (await store.add('AAAAA-AAAAA')).child
    const b = (await store.add('BBBBB-BBBBB')).child
    store.rename(a.id, `  ${'x'.repeat(50)}  `)
    expect(store.children[0].name).toHaveLength(MAX_CHILD_NAME)
    store.select(b.id)
    store.remove(b.id)
    expect(store.selected?.id).toBe(a.id)
    store.remove(a.id)
    expect(store.selected).toBeNull()
  })

  it('offers only the 7- and 30-day periods', () => {
    const store = useParentStore()
    store.setPeriod(30)
    expect(store.period).toBe(30)
    store.setPeriod(14)
    expect(store.period).toBe(30)
  })
})

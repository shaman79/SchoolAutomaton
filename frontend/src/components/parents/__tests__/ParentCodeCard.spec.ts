/**
 * The parent code on the child's device: offered only once we know there is none (a failed load
 * never offers "Create" — that would replace a code a parent uses), shown again with a QR code and
 * a link to send, replaced or stopped only after an inline "are you sure".
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { getParentCode: vi.fn(), createParentCode: vi.fn(), deleteParentCode: vi.fn() } }
})
vi.mock('@/lib/share', () => ({
  qrDataUrl: vi.fn(async (url: string) => `data:image/png;base64,${btoa(url)}`),
  shareOrCopy: vi.fn(async () => 'copied'),
  writeClipboard: vi.fn(async () => true),
}))

import ParentCodeCard from '@/components/parents/ParentCodeCard.vue'
import { i18n } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import { shareOrCopy } from '@/lib/share'
import { clearToasts, stubDom } from '@/views/__tests__/fixtures'

const mocked = api as unknown as Record<string, Mock>
const t = i18n.global.t
const CODE = { code: 'ABCDE-FGHJK', created_at: '2026-11-20T10:00:00Z', last_used_at: null }

async function render() {
  const w = mount(ParentCodeCard, { global: { plugins: [i18n] } })
  await flushPromises()
  return w
}
const button = (w: ReturnType<typeof mount>, text: string) => w.findAll('button').find((b) => b.text() === text)

beforeEach(() => {
  stubDom()
  vi.clearAllMocks()
  clearToasts()
})

it('creates a code and shows it with its QR code and link', async () => {
  mocked.getParentCode.mockResolvedValue(null)
  mocked.createParentCode.mockResolvedValue(CODE)
  const w = await render()
  expect(w.text()).toContain(t('parent_code.intro'))
  await button(w, t('parent_code.create'))!.trigger('click')
  await flushPromises()
  expect(w.find('.sa-pcode__value').text()).toBe('ABCDE-FGHJK')
  const qr = w.find('.sa-pcode__qr img')
  expect(atob(qr.attributes('src')!.split(',')[1])).toBe(`${window.location.origin}/parent?code=ABCDE-FGHJK`)
  expect(w.text()).toContain(t('parent_code.never_used'))
  await button(w, t('parent_code.share'))!.trigger('click')
  expect(shareOrCopy).toHaveBeenCalledWith(expect.objectContaining({ url: `${window.location.origin}/parent?code=ABCDE-FGHJK` }))
})

it('never offers "Create" when it could not tell whether a code exists', async () => {
  mocked.getParentCode.mockRejectedValueOnce(new ApiError(503, 'busy'))
  const w = await render()
  expect(button(w, t('parent_code.create'))).toBeUndefined()
  mocked.getParentCode.mockResolvedValue(CODE)
  await button(w, t('common.retry'))!.trigger('click')
  await flushPromises()
  expect(w.text()).toContain(t('parent_code.active'))
})

it('replaces the code only after asking', async () => {
  mocked.getParentCode.mockResolvedValue(CODE)
  mocked.createParentCode.mockResolvedValue({ ...CODE, code: 'ZZZZZ-ZZZZZ' })
  const w = await render()
  await button(w, t('parent_code.show'))!.trigger('click')
  await button(w, t('parent_code.new_code'))!.trigger('click')
  expect(mocked.createParentCode).not.toHaveBeenCalled()
  expect(w.text()).toContain(t('parent_code.new_confirm'))
  await button(w, t('parent_code.new_yes'))!.trigger('click')
  await flushPromises()
  expect(w.find('.sa-pcode__value').text()).toBe('ZZZZZ-ZZZZZ')
})

it('stops sharing only after asking', async () => {
  mocked.getParentCode.mockResolvedValue(CODE)
  mocked.deleteParentCode.mockResolvedValue(undefined)
  const w = await render()
  await button(w, t('parent_code.show'))!.trigger('click')
  await button(w, t('parent_code.stop'))!.trigger('click')
  await button(w, t('parent_code.cancel'))!.trigger('click')
  expect(mocked.deleteParentCode).not.toHaveBeenCalled()
  await button(w, t('parent_code.stop'))!.trigger('click')
  await button(w, t('parent_code.stop_yes'))!.trigger('click')
  await flushPromises()
  expect(mocked.deleteParentCode).toHaveBeenCalledOnce()
  expect(button(w, t('parent_code.create'))).toBeDefined()
})

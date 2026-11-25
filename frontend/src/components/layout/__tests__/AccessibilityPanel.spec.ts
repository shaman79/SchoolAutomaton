/**
 * Settings (⚙, on every screen) is the way in for parents: on a device that learns, the overview
 * with the parent code; on any device, following a child from this phone. Each link closes the panel.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'

const stored = vi.hoisted(() => ({ code: null as string | null }))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, getResumeCode: () => stored.code, setResumeCode: vi.fn() }
})

import AccessibilityPanel from '@/components/layout/AccessibilityPanel.vue'
import { i18n } from '@/i18n'
import { makeRouter, stubDom } from '@/views/__tests__/fixtures'

const t = i18n.global.t

async function render() {
  const w = mount(AccessibilityPanel, {
    props: { open: true },
    global: { plugins: [createPinia(), i18n, makeRouter()], stubs: { teleport: true, ResumeCodeCard: true } },
  })
  await flushPromises()
  return w
}
const link = (w: Awaited<ReturnType<typeof render>>, text: string) =>
  w.findAll('a').find((a) => a.text().includes(text))

beforeEach(() => {
  stubDom()
  setActivePinia(createPinia())
})

it("on the child's device it leads to the overview with the parent code", async () => {
  stored.code = 'K7QF-2M9X'
  const w = await render()
  expect(w.text()).toContain(t('parent.settings_title'))
  expect(link(w, t('parents.link'))?.attributes('href')).toBe('/parents')
  expect(link(w, t('parent.settings_follow'))?.attributes('href')).toBe('/parent')
  await link(w, t('parents.link'))!.trigger('click')
  expect(w.emitted('close')).toBeTruthy()
})

it('on a device without a learner it offers following a child', async () => {
  stored.code = null
  const w = await render()
  expect(link(w, t('parents.link'))).toBeUndefined()
  expect(link(w, t('parent.settings_follow'))?.attributes('href')).toBe('/parent')
})

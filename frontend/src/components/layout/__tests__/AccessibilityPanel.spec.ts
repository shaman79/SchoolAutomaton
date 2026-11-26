/**
 * Settings (⚙, on every screen) is the way in for parents: one "For parents" link (the overview +
 * parent code on a device that learns; following a child elsewhere), which closes the panel.
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

beforeEach(() => {
  stubDom()
  setActivePinia(createPinia())
})

it("one way in for parents, worded for this device", async () => {
  stored.code = 'K7QF-2M9X'
  const w = await render()
  const links = w.findAll('a').filter((a) => a.text().includes(t('parent.title')))
  expect(links.map((a) => a.attributes('href'))).toEqual(['/parent'])
  expect(w.text()).toContain(t('parent.settings_hint_device'))
  await links[0].trigger('click')
  expect(w.emitted('close')).toBeTruthy()
})

it('on a device without a learner the same link says it follows a child', async () => {
  stored.code = null
  const w = await render()
  expect(w.findAll('a').filter((a) => a.attributes('href') === '/parent')).toHaveLength(1)
  expect(w.text()).toContain(t('parent.settings_hint_other'))
})

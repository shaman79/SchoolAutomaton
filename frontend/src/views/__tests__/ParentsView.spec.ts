/**
 * "Overview for parents" on the child's own device: the period can be 7 or 30 days (the latest
 * choice wins even when answers arrive out of order), and a device without a learner points a parent
 * to the parent view.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { beforeEach, expect, it, vi, type Mock } from 'vitest'

const stored = vi.hoisted(() => ({ code: 'OLD1-CODE' as string | null }))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: { getSummary: vi.fn(), getParentCode: vi.fn() },
    getResumeCode: () => stored.code,
    setResumeCode: vi.fn(),
  }
})

import { i18n } from '@/i18n'
import { api } from '@/lib/api'
import ParentsView from '@/views/ParentsView.vue'
import type { ParentSummary } from '@/types/session'

import { makeRouter, stubDom } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
const t = i18n.global.t
let pinia: Pinia

function summary(days: number): ParentSummary {
  return { days, active_days: days === 30 ? 9 : 2, lessons: 1, quizzes_completed: 0, answers: 4, correct: 3,
           due_reviews: 1, topics: [], misconceptions: [] }
}
async function render() {
  const w = mount(ParentsView, { global: { plugins: [pinia, i18n, makeRouter()] } })
  await flushPromises()
  return w
}

beforeEach(() => {
  stubDom()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  stored.code = 'OLD1-CODE'
  mocked.getParentCode.mockResolvedValue(null)
  mocked.getSummary.mockImplementation(async (days: number) => summary(days))
})

it('switches between the last 7 and 30 days; the latest choice wins', async () => {
  const w = await render()
  expect(mocked.getSummary).toHaveBeenCalledWith(7)
  expect(w.text()).toContain(t('parents.of_days', { n: 2, total: 7 }))
  // The 30-day answer comes late, after the user already went back to 7.
  let release30: (s: ParentSummary) => void = () => {}
  mocked.getSummary.mockImplementationOnce(() => new Promise((r) => (release30 = r)))
  await w.find('input[type="radio"][value="30"]').setValue(true)
  await w.find('input[type="radio"][value="7"]').setValue(true)
  await flushPromises()
  release30(summary(30))
  await flushPromises()
  expect(w.text()).toContain(t('parents.of_days', { n: 2, total: 7 }))
  expect(w.text()).toContain(t('parents.subtitle', { n: 7 }))
  // On the child's own device the review can be started right here.
  expect(w.text()).toContain(t('daily.cta'))
})

it('a device without a learner points a parent to the parent view', async () => {
  stored.code = null
  const w = await render()
  expect(mocked.getSummary).not.toHaveBeenCalled()
  expect(w.find('a[href="/parent"]').text()).toContain(t('parents.open_parent'))
})

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import DailyReviewCard from '@/components/common/DailyReviewCard.vue'
import { i18n, setLocale } from '@/i18n'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: { getDue: vi.fn() },
  getResumeCode: () => 'ABCD-EFGH',
  setResumeCode: vi.fn(),
}))

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/daily', name: 'daily', component: { template: '<div />' } },
  ],
})

function mountCard() {
  return mount(DailyReviewCard, { global: { plugins: [createPinia(), i18n, router] } })
}

describe('DailyReviewCard', () => {
  afterEach(() => setLocale('en'))

  it('invites to today’s review with a correctly declined Czech count', async () => {
    ;(api.getDue as Mock).mockResolvedValue({ items: [{}, {}, {}], composition: {} })
    setLocale('cs')
    const w = mountCard()
    await flushPromises()
    expect(w.text()).toContain('Zalij svou zahrádku')
    expect(w.text()).toContain('3 otázky čekají na zopakování')
    expect(w.find('a').attributes('href')).toBe('/daily')
  })

  it('renders nothing when nothing is due or the load fails', async () => {
    ;(api.getDue as Mock).mockResolvedValue({ items: [], composition: {} })
    const empty = mountCard()
    await flushPromises()
    expect(empty.find('a').exists()).toBe(false)

    ;(api.getDue as Mock).mockRejectedValue(new Error('offline'))
    const failed = mountCard()
    await flushPromises()
    expect(failed.find('a').exists()).toBe(false)
  })
})

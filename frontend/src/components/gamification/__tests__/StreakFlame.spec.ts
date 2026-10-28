/**
 * A streak of 0 (a new learner, or one back after a gap that couldn't be bridged) reads as an
 * invitation, never as a loss: no bare "0", no "lost"/"broken" wording — in English and Czech.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import StreakFlame from '@/components/gamification/StreakFlame.vue'
import { i18n, setLocale } from '@/i18n'
import { api } from '@/lib/api'
import { usePrefsStore } from '@/stores/prefs'
import { useSessionStore } from '@/stores/session'
import type { StreakInfo } from '@/types/session'
import StatsView from '@/views/StatsView.vue'
import { stubDom } from '@/views/__tests__/fixtures'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      getTree: vi.fn().mockResolvedValue({ nodes: [], edges: [] }),
      getDue: vi.fn().mockResolvedValue({ items: [], composition: {} }),
      getGamification: vi.fn(),
    },
    getResumeCode: () => 'ABCD-EFGH',
    setResumeCode: vi.fn(),
  }
})

const LOSS_WORDS = /lost|broke|ztrat|přeruš|0-day|0 dn/i

function flame(current: number, extra: Partial<StreakInfo> = {}, showLabel = true) {
  const streak = { current, longest: 7, freeze_inventory: 2, is_perfect: true, frozen: false, ...extra }
  return mount(StreakFlame, { props: { streak, showLabel }, global: { plugins: [i18n] } })
}

beforeEach(() => stubDom()) // jsdom has no matchMedia (reduced-motion check)
afterEach(() => setLocale('en'))

describe('StreakFlame at 0', () => {
  it.each([
    ['en', 'Start a streak!'],
    ['cs', 'Začni sérii!'],
  ])('invites to start one (%s)', (locale, invitation) => {
    setLocale(locale)
    const w = flame(0)
    expect(w.text()).toBe(invitation)
    expect(w.attributes('aria-label')).toBe(invitation)
    expect(w.classes()).toContain('sa-streak--none')
    expect(w.text()).not.toMatch(LOSS_WORDS)
  })

  it.each(['en', 'cs'])('shows no bare "0" in the compact header form (%s)', (locale) => {
    setLocale(locale)
    const w = flame(0, {}, false)
    expect(w.text()).toBe('')
    expect(w.find('.sa-streak__count').exists()).toBe(false)
    expect(w.attributes('aria-label')).toBe(locale === 'cs' ? 'Začni sérii!' : 'Start a streak!')
  })

  it('counts with correct Czech plurals once there is a streak', () => {
    setLocale('cs')
    expect(flame(3).text()).toBe('3 dny v řadě')
    expect(flame(5).text()).toBe('5 dní v řadě')
    setLocale('en')
    expect(flame(1, {}, false).find('.sa-streak__count').text()).toBe('1')
  })
})

describe('the progress screen with a streak of 0', () => {
  it.each([
    ['en', 'Start a streak!', 'Longest: 7'],
    ['cs', 'Začni sérii!', 'Nejdelší: 7'],
  ])('invites and keeps the personal best (%s)', async (locale, invitation, best) => {
    setActivePinia(createPinia())
    usePrefsStore().locale = locale // the UI language follows the prefs store
    const session = useSessionStore()
    const snapshot = {
      level: 2,
      total_xp: 150,
      xp_to_next: 40,
      level_progress_pct: 0.5,
      streak: { current: 0, longest: 7, freeze_inventory: 2, is_perfect: true, frozen: false },
      daily_goal: 'regular',
      daily_progress_xp: 0,
      badges: [],
    }
    session.gamification = snapshot
    vi.mocked(api.getGamification).mockResolvedValue(snapshot) // the screen re-reads it on open
    const blank = { template: '<div />' }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: ['home', 'daily', 'parents', 'history', 'stats'].map((name) => ({
        path: name === 'home' ? '/' : `/${name}`,
        name,
        component: blank,
      })),
    })
    const w = mount(StatsView, { global: { plugins: [i18n, router] } })
    await flushPromises()

    const tile = w.find('.sa-stats__tiles .sa-card')
    expect(tile.text()).toContain(invitation)
    expect(tile.text()).toContain(best)
    expect(tile.text()).not.toMatch(LOSS_WORDS)
  })
})

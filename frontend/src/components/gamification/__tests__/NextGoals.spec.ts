/**
 * "Within reach": the closest badges not earned yet, each with how to earn it and how far along —
 * never earned ones, closest first, then the catalogue order (the easy ones come first there).
 */
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'

import NextGoals from '@/components/gamification/NextGoals.vue'
import type { BadgeInfo } from '@/components/gamification/types'
import { i18n } from '@/i18n'

const t = i18n.global.t

function badge(code: string, num = 0, den = 1, unlocked = false): BadgeInfo {
  return {
    code, title: `T-${code}`, description: `How to earn ${code}`, tier: 1,
    unlocked_at: unlocked ? '2026-11-20T10:00:00Z' : null,
    progress_numerator: num, progress_denominator: den, icon_url: null,
  }
}

it('the closest unearned badges first, each with how to earn it and what is left', () => {
  const w = mount(NextGoals, {
    props: {
      badges: [badge('first'), badge('done', 1, 1, true), badge('sharp', 7, 10), badge('poly', 1, 2), badge('late')],
    },
    global: { plugins: [i18n] },
  })
  const titles = w.findAll('.sa-goals__title').map((p) => p.text())
  expect(titles).toEqual(['T-sharp', 'T-poly', 'T-first'])
  expect(w.text()).toContain('How to earn sharp')
  expect(w.text()).toContain(t('gamification.goal_left', { n: 3 }, 3))
  // A yes/no badge has no counter to show.
  expect(w.findAll('.sa-goals__item')[2].find('[role="progressbar"]').exists()).toBe(false)
})

it('says so when every badge is earned', () => {
  const w = mount(NextGoals, { props: { badges: [badge('a', 1, 1, true)] }, global: { plugins: [i18n] } })
  expect(w.text()).toBe(t('gamification.goals_all_done'))
})

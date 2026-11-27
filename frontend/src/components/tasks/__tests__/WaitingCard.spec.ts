/**
 * Home: tasks from a parent, in one list at the top. Each row is one tap: a ready task opens the
 * lesson/quiz, a started one continues, one being prepared (or that failed) goes through the loading
 * screen. Started first; three rows, then fold. The learner's own unfinished session is not here
 * (ContinueRow).
 */
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'

import WaitingCard from '@/components/tasks/WaitingCard.vue'
import { i18n } from '@/i18n'
import type { Assignment } from '@/types/session'
import { makeRouter } from '@/views/__tests__/fixtures'

const t = i18n.global.t
const progress = (position: number, total: number) => ({ position, total, completed: false, last_active_at: null })

function task(id: number, over: Partial<Assignment> = {}): Assignment {
  return {
    id, request_id: `r${id}`, mode: 'test', title: `Task ${id}`, subject: 'math', created_at: null,
    status: 'ready', progress: null, result: null, ...over,
  }
}
function render(tasks: Assignment[]) {
  return mount(WaitingCard, { props: { tasks }, global: { plugins: [i18n, makeRouter()] } })
}

it('one tap each, the right way for where it is; started ones first', () => {
  const w = render([
    task(1, { status: 'preparing' }),
    task(2, { mode: 'study', status: 'started', progress: progress(3, 8) }),
    task(3),
    task(4),
  ])
  expect(w.find('h2').text()).toBe(t('tasks.waiting_title'))
  const links = w.findAll('a')
  expect(links.map((a) => a.attributes('href'))).toEqual(['/lesson/r2', '/loading/r1', '/test/r3'])
  expect(links[0].text()).toContain(t('common.continue'))
  expect(links[0].text()).toContain(t('progress.part', { current: 3, total: 8 }))
  expect(links[1].text()).toContain(t('tasks.preparing'))
  expect(links[2].text()).toContain(t('tasks.start'))
  // The fourth is folded away.
  expect(w.text()).toContain(t('tasks.more', { n: 1 }))
})

it('shows a tidy title', () => {
  const w = render([task(1, { title: 'zlomky na obrázcích (vysvětlení zlomků pomocí obrázků)' })])
  expect(w.find('a').text()).toContain('Zlomky na obrázcích')
  expect(w.find('a').text()).not.toContain('vysvětlení')
})

it('a task that could not be prepared is retried from the loading screen', () => {
  const w = render([task(1, { status: 'failed' })])
  expect(w.find('a').attributes('href')).toBe('/loading/r1')
  expect(w.text()).toContain(t('tasks.failed_hint'))
})

it('shows three and folds the rest away', async () => {
  const w = render([1, 2, 3, 4, 5].map((n) => task(n)))
  expect(w.findAll('li')).toHaveLength(3)
  await w.findAll('button').find((b) => b.text() === t('tasks.more', { n: 2 }))!.trigger('click')
  expect(w.findAll('li')).toHaveLength(5)
})

it('renders nothing when nothing waits', () => {
  expect(render([]).find('section').exists()).toBe(false)
})

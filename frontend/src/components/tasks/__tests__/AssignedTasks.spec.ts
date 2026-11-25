/**
 * The child's home: tasks from a parent, each one tap away — a ready one opens the lesson/quiz, an
 * unfinished one continues, one still being prepared (or that failed) goes through the loading
 * screen. After three, the rest fold away.
 */
import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'

import AssignedTasks from '@/components/tasks/AssignedTasks.vue'
import { i18n } from '@/i18n'
import type { Assignment } from '@/types/session'
import { makeRouter } from '@/views/__tests__/fixtures'

const t = i18n.global.t

function task(id: number, over: Partial<Assignment> = {}): Assignment {
  return {
    id, request_id: `r${id}`, mode: 'test', title: `Task ${id}`, subject: 'math', created_at: null,
    status: 'ready', progress: null, result: null, ...over,
  }
}

function render(tasks: Assignment[]) {
  return mount(AssignedTasks, { props: { tasks }, global: { plugins: [i18n, makeRouter()] } })
}

it('opens each task the right way for where it is', () => {
  const w = render([
    task(1),
    task(2, { mode: 'study', status: 'started', progress: { position: 3, total: 8, completed: false, last_active_at: null } }),
    task(3, { status: 'preparing' }),
  ])
  const links = w.findAll('a')
  expect(links.map((a) => a.attributes('href'))).toEqual(['/test/r1', '/lesson/r2', '/loading/r3'])
  expect(links.map((a) => a.text())).toEqual([t('tasks.start'), t('common.continue'), t('tasks.preparing')])
  expect(w.text()).toContain(t('progress.part', { current: 3, total: 8 }))
})

it('a task that could not be prepared is retried from the loading screen', () => {
  const w = render([task(1, { status: 'failed' })])
  expect(w.find('a').attributes('href')).toBe('/loading/r1')
  expect(w.text()).toContain(t('tasks.failed_hint'))
})

it('shows three and folds the rest away', async () => {
  const w = render([1, 2, 3, 4, 5].map((n) => task(n)))
  expect(w.findAll('li')).toHaveLength(3)
  const more = w.findAll('button').find((b) => b.text() === t('tasks.show_all', { n: 5 }))!
  await more.trigger('click')
  expect(w.findAll('li')).toHaveLength(5)
})

it('renders nothing without tasks', () => {
  expect(render([]).find('section').exists()).toBe(false)
})

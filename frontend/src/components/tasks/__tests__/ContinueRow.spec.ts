/**
 * Home: the lesson/quiz the learner was last in, as one quiet row — one tap continues exactly there;
 * × hides it on this device until they work on it again, and says where it still is.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it } from 'vitest'

import ContinueRow from '@/components/tasks/ContinueRow.vue'
import { i18n } from '@/i18n'
import { hideContinue, isContinueHidden } from '@/lib/hiddenContinue'
import type { LearningSessionSummary } from '@/types/session'
import { makeRouter } from '@/views/__tests__/fixtures'

const t = i18n.global.t

function lesson(over: Partial<LearningSessionSummary> = {}): LearningSessionSummary {
  return {
    request_id: 'r1', mode: 'study', status: 'ready', lesson_id: 7, quiz_id: null,
    title: 'zlomky na obrázcích (vysvětlení zlomků pomocí obrázků)', subject: 'math', created_at: null,
    progress: { position: 3, total: 12, completed: false, last_active_at: '2026-11-20T10:00:00Z' },
    ...over,
  }
}

afterEach(() => localStorage.clear())

it('one tap continues where they were', () => {
  const w = mount(ContinueRow, {
    props: { session: lesson() },
    global: { plugins: [i18n, makeRouter()] },
  })
  const link = w.find('a')
  expect(link.attributes('href')).toBe('/lesson/r1')
  expect(link.text()).toContain('Zlomky na obrázcích')
  expect(link.text()).toContain(t('progress.part', { current: 3, total: 12 }))
  expect(link.text()).toContain(t('common.continue'))
})

it('a quiz opens the quiz', () => {
  const w = mount(ContinueRow, {
    props: { session: lesson({ mode: 'test', lesson_id: null, quiz_id: 3 }) },
    global: { plugins: [i18n, makeRouter()] },
  })
  expect(w.find('a').attributes('href')).toBe('/test/r1')
})

it('× hides it here, says where it still is, and keeps the focus on the page', async () => {
  const w = mount(ContinueRow, {
    props: { session: lesson() },
    global: { plugins: [i18n, makeRouter()] },
    attachTo: document.body,
  })
  const hide = w.find('button')
  expect(hide.attributes('aria-label')).toBe(t('tasks.hide_continue', { title: 'Zlomky na obrázcích' }))
  await hide.trigger('click')
  await flushPromises()
  expect(w.find('section').exists()).toBe(false)
  const note = w.find('p')
  expect(note.text()).toContain(t('history.title'))
  expect(note.find('a').attributes('href')).toBe('/history')
  expect(document.activeElement).toBe(note.element)
  expect(isContinueHidden(lesson())).toBe(true)
  w.unmount()
})

it('comes back once they work on it again (or for something else)', () => {
  hideContinue(lesson())
  expect(isContinueHidden(lesson())).toBe(true)
  const later = lesson({
    progress: { position: 4, total: 12, completed: false, last_active_at: '2026-11-25T08:00:00Z' },
  })
  expect(isContinueHidden(later)).toBe(false)
  expect(isContinueHidden(lesson({ request_id: 'r2' }))).toBe(false)
})

it('without storage it is simply shown', () => {
  localStorage.setItem('sa_hidden_continue', '{not json')
  expect(isContinueHidden(lesson())).toBe(false)
})

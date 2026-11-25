/**
 * A parent's own phone (/parent): add a child from the shared link (the code leaves the address bar),
 * refuse the child's own learning code, give a task and follow it until it's ready, turn a weak topic
 * into a quiz task, switch the period, and say plainly when a code stopped working.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    api: {
      parentChild: vi.fn(),
      parentSummary: vi.fn(),
      parentAssignments: vi.fn(),
      parentAssign: vi.fn(),
      parentRetryAssignment: vi.fn(),
      parentRemoveAssignment: vi.fn(),
    },
  }
})

import { i18n } from '@/i18n'
import { ApiError, api } from '@/lib/api'
import { useParentStore } from '@/stores/parent'
import type { Assignment, ParentSummary } from '@/types/session'
import ParentView from '@/views/ParentView.vue'

import { clearToasts, makeRouter, stubDom } from './fixtures'

const mocked = api as unknown as Record<string, Mock>
const t = i18n.global.t
let pinia: Pinia
const mounted: { unmount: () => void }[] = []

function summary(days = 7): ParentSummary {
  return {
    days, active_days: 2, lessons: 1, quizzes_completed: 1, answers: 5, correct: 3, due_reviews: 2,
    topics: [{ concept_id: 1, title: 'Zlomky', subject: 'math', answers: 3, correct: 1, status: 'practice' }],
    misconceptions: [],
  }
}
function task(over: Partial<Assignment> = {}): Assignment {
  return {
    id: 1, request_id: 'r1', mode: 'test', title: 'Násobilka 7', subject: 'math',
    created_at: new Date().toISOString(), status: 'preparing', progress: null, result: null, ...over,
  }
}

async function mountAt(path = '/parent') {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  // Attached, so focus moves can be checked.
  const w = mount(ParentView, { global: { plugins: [pinia, i18n, router] }, attachTo: document.body })
  mounted.push(w)
  await flushPromises()
  return { w, router }
}

function follow(name = 'Anička') {
  const store = useParentStore()
  store.children = [{ id: 'c1', code: 'ABCDE-FGHJK', name, addedAt: '2026-11-01T00:00:00Z' }]
  store.selectedId = 'c1'
  return store
}

/** Submit the form a field belongs to (as Enter / the submit button would). */
async function submitFormOf(w: ReturnType<typeof mount>, selector: string) {
  const el = w.find(selector).element as HTMLInputElement | HTMLTextAreaElement
  el.form!.dispatchEvent(new Event('submit'))
  await flushPromises()
}

function button(w: ReturnType<typeof mount>, text: string) {
  const b = w.findAll('button').find((x) => x.text().trim() === text)
  if (!b) throw new Error(`no button "${text}"`)
  return b
}

beforeEach(() => {
  stubDom()
  Element.prototype.scrollIntoView = vi.fn()
  vi.useFakeTimers()
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  clearToasts()
  mocked.parentChild.mockResolvedValue({ school_year: 3, education_locale: 'en-US' })
  mocked.parentSummary.mockImplementation(async (_code: string, days: number) => summary(days))
  mocked.parentAssignments.mockResolvedValue([])
})
afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  vi.useRealTimers()
})

it('adds a child from the shared link, takes the code out of the address bar, and asks for a name', async () => {
  const { w, router } = await mountAt('/parent?code=abcde-fghjk')
  expect(router.currentRoute.value.query).toEqual({})
  expect(mocked.parentChild).toHaveBeenCalledWith('ABCDE-FGHJK')
  const name = w.find('#sa-child-name')
  expect(name.exists()).toBe(true)
  await name.setValue('Anička')
  await submitFormOf(w, '#sa-child-name')
  expect(w.find('.sa-pview__name').text()).toBe('Anička')
  expect(useParentStore().children[0]).toMatchObject({ code: 'ABCDE-FGHJK', name: 'Anička' })
  // The child's class, the tasks and the overview load for them.
  expect(w.text()).toContain('Grade 3')
  expect(mocked.parentSummary).toHaveBeenCalledWith('ABCDE-FGHJK', 7)
})

it("refuses the child's own learning code without asking the server", async () => {
  const { w } = await mountAt()
  await w.find('#sa-parent-code').setValue('K7QF-2M9X')
  await submitFormOf(w, '#sa-parent-code')
  expect(mocked.parentChild).not.toHaveBeenCalled()
  expect(w.find('#sa-parent-code-err').text()).toBe(
    t('parent.resume_code_given', { overview: t('parents.link') }),
  )
  expect(useParentStore().children).toHaveLength(0)
})

it('an unknown code says to check it', async () => {
  mocked.parentChild.mockRejectedValue(new ApiError(401, 'Unknown parent code'))
  const { w } = await mountAt()
  await w.find('#sa-parent-code').setValue('ZZZZZ-ZZZZZ')
  await submitFormOf(w, '#sa-parent-code')
  expect(w.find('#sa-parent-code-err').text()).toBe(t('parent.not_found'))
})

it('gives a task and follows it until it is ready', async () => {
  follow()
  mocked.parentAssign.mockResolvedValue({
    decision: { type: 'proceed', request_id: 'r1', mode: 'test', intent: {} },
    assignment: task(),
  })
  const { w } = await mountAt()
  expect(w.text()).toContain(t('parent.tasks_empty'))
  await button(w, t('parent.give')).trigger('click')
  await flushPromises()
  const textarea = w.find('textarea')
  expect(document.activeElement).toBe(textarea.element)
  await textarea.setValue('násobilka 7')
  await w.find('input[type="radio"][value="test"]').setValue(true)
  await submitFormOf(w, 'textarea')
  expect(mocked.parentAssign).toHaveBeenCalledWith('ABCDE-FGHJK', 'násobilka 7', 'test')
  expect(w.find('textarea').exists()).toBe(false) // the composer closes
  expect(w.text()).toContain(t('parent.status.preparing'))

  mocked.parentAssignments.mockResolvedValue([task({ status: 'ready' })])
  await vi.advanceTimersByTimeAsync(5_000)
  await flushPromises()
  expect(w.text()).toContain(t('parent.status.ready'))
})

it('a topic worth practising becomes a quiz task in one tap', async () => {
  follow()
  const { w } = await mountAt()
  await button(w, t('parent.assign_topic')).trigger('click')
  await flushPromises()
  expect((w.find('textarea').element as HTMLTextAreaElement).value).toBe('Zlomky')
  expect((w.find('input[type="radio"][value="test"]').element as HTMLInputElement).checked).toBe(true)
  // On the parent's phone the review is not started from here.
  expect(w.text()).not.toContain(t('daily.cta'))
})

it('a clarifying question offers suggestions that refine the text', async () => {
  follow()
  mocked.parentAssign.mockResolvedValueOnce({
    decision: { type: 'clarify', request_id: 'x', question: 'Which tables?', suggestions: ['the 7s'] },
    assignment: null,
  })
  mocked.parentAssign.mockResolvedValueOnce({ decision: { type: 'proceed' }, assignment: task() })
  const { w } = await mountAt()
  await button(w, t('parent.give')).trigger('click')
  await flushPromises()
  await w.find('textarea').setValue('times tables')
  await submitFormOf(w, 'textarea')
  expect(w.text()).toContain('Which tables?')
  await button(w, 'the 7s').trigger('click')
  await flushPromises()
  expect(mocked.parentAssign).toHaveBeenLastCalledWith('ABCDE-FGHJK', 'times tables — the 7s', 'study')
})

it('says how many tasks may wait when there are too many', async () => {
  follow()
  mocked.parentAssign.mockRejectedValue(new ApiError(409, 'too_many_tasks'))
  const { w } = await mountAt()
  await button(w, t('parent.give')).trigger('click')
  await flushPromises()
  await w.find('textarea').setValue('more')
  await submitFormOf(w, 'textarea')
  expect(w.find('[role="alert"]').text()).toBe(t('parent.too_many', { n: 10 }))
})

it('switches the overview to the last 30 days', async () => {
  const store = follow()
  const { w } = await mountAt()
  await w.find('input[type="radio"][value="30"]').setValue(true)
  await flushPromises()
  expect(mocked.parentSummary).toHaveBeenLastCalledWith('ABCDE-FGHJK', 30)
  expect(store.period).toBe(30)
  expect(w.text()).toContain(t('parents.subtitle', { n: 30 }))
})

it('says plainly when a code stopped working, and keeps the child until removed', async () => {
  const store = follow()
  mocked.parentChild.mockRejectedValue(new ApiError(401, 'Unknown parent code'))
  const { w } = await mountAt()
  expect(w.text()).toContain(t('parent.revoked_title'))
  expect(store.children[0].revoked).toBe(true)
  await button(w, t('parent.remove_child')).trigger('click')
  await button(w, t('parent.remove_yes')).trigger('click')
  await flushPromises()
  expect(store.children).toHaveLength(0)
  expect(w.find('#sa-parent-code').exists()).toBe(true) // back to "add a child"
})

it('takes a task back after asking', async () => {
  follow()
  mocked.parentAssignments.mockResolvedValue([task({ status: 'ready' })])
  mocked.parentRemoveAssignment.mockResolvedValue(undefined)
  const { w } = await mountAt()
  await button(w, t('parent.remove')).trigger('click')
  expect(w.text()).toContain(t('parent.remove_confirm'))
  const confirm = w.find('.sa-alist__confirm')
  await confirm.findAll('button')[0].trigger('click')
  await flushPromises()
  expect(mocked.parentRemoveAssignment).toHaveBeenCalledWith('ABCDE-FGHJK', 1)
  expect(w.text()).toContain(t('parent.tasks_empty'))
})

it('a period switched while the page loads is the one shown', async () => {
  follow()
  let release: (s: ParentSummary) => void = () => {}
  mocked.parentSummary.mockImplementationOnce(() => new Promise((r) => (release = r)))
  const router = makeRouter()
  await router.push('/parent')
  const w = mount(ParentView, { global: { plugins: [pinia, i18n, router] } })
  mounted.push(w)
  await flushPromises()
  useParentStore().setPeriod(30) // switched before the first answer came
  release(summary(7))
  await flushPromises()
  expect(mocked.parentSummary).toHaveBeenLastCalledWith('ABCDE-FGHJK', 30)
  expect(w.text()).toContain(t('parents.of_days', { n: 2, total: 30 }))
})


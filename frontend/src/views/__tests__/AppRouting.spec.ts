/**
 * Opening another lesson/quiz (same route, new :sessionId) must build a fresh view — a reused one
 * kept the previous lesson's state and never re-ran its loading.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import { defineComponent, h, onMounted } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, api: { getMe: vi.fn() }, getResumeCode: () => null }
})

import App from '@/App.vue'
import { i18n } from '@/i18n'

import { stubDom } from './fixtures'

it('navigating /lesson/A → /lesson/B mounts a new view', async () => {
  stubDom()
  const mounted: string[] = []
  const Lesson = defineComponent({
    props: { sessionId: { type: String, required: true } },
    setup(props) {
      onMounted(() => mounted.push(props.sessionId))
      return () => h('div', `lesson ${props.sessionId}`)
    },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/lesson/:sessionId', component: Lesson, props: true },
    ],
  })
  await router.push('/lesson/A')
  await router.isReady()
  mount(App, {
    global: {
      plugins: [createPinia(), i18n, router],
      stubs: { AppHeader: true, AppFooter: true, AccessibilityPanel: true, ToastHost: true },
    },
  })
  await flushPromises()
  await router.push('/lesson/B')
  await flushPromises()
  expect(mounted).toEqual(['A', 'B'])
})

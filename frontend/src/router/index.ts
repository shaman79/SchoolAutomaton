import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const ADMIN_TOKEN_KEY = 'sa_admin_token'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
  {
    path: '/loading/:sessionId',
    name: 'loading',
    component: () => import('@/views/LoadingView.vue'),
    props: true,
  },
  {
    path: '/lesson/:sessionId',
    name: 'lesson',
    component: () => import('@/views/LessonView.vue'),
    props: true,
  },
  {
    path: '/test/:sessionId',
    name: 'test',
    component: () => import('@/views/TestView.vue'),
    props: true,
  },
  {
    path: '/results/:sessionId',
    name: 'results',
    component: () => import('@/views/ResultsView.vue'),
    props: true,
  },
  { path: '/history', name: 'history', component: () => import('@/views/HistoryView.vue') },
  { path: '/resume', name: 'resume', component: () => import('@/views/ResumeView.vue') },
  { path: '/admin/login', name: 'admin-login', component: () => import('@/views/admin/AdminLoginView.vue') },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/admin/AdminDashboardView.vue'),
    meta: { requiresAdmin: true },
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFoundView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  if (to.meta.requiresAdmin && !localStorage.getItem(ADMIN_TOKEN_KEY)) {
    return { name: 'admin-login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
export { ADMIN_TOKEN_KEY }

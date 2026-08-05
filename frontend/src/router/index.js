import { createRouter, createWebHistory } from 'vue-router'
import { currentUser } from '@/composables/useAuth.js'

// 认证初始化标记 — App.vue onMounted 中 initAuth() 完成后设为 true
let authInitialized = false
let _authResolve = null
const authReady = new Promise(resolve => { _authResolve = resolve })
export function markAuthReady() { authInitialized = true; _authResolve() }

const routes = [
  {
    path: '/',
    redirect: '/master-bank',
  },
  {
    path: '/login',
    component: () => import('@/layouts/BlankLayout.vue'),
    children: [
      {
        path: '',
        name: 'login',
        component: () => import('@/views/LoginView.vue'),
      },
    ],
  },
  {
    path: '/',
    component: () => import('@/layouts/AuthenticatedLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: 'master-bank',
        name: 'master-bank',
        component: () => import('@/views/MasterBankView.vue'),
      },
      {
        path: 'chat/:sessionId?',
        name: 'chat',
        component: () => import('@/views/ChatView.vue'),
      },
      {
        path: 'jd',
        name: 'jd',
        component: () => import('@/views/JdView.vue'),
      },
      {
        path: 'interview',
        name: 'interview',
        component: () => import('@/views/InterviewView.vue'),
      },
      {
        path: 'practice',
        name: 'practice',
        component: () => import('@/views/PracticeView.vue'),
      },
      {
        path: 'practice/decks',
        name: 'practice-decks',
        component: () => import('@/views/PracticeDecksView.vue'),
      },
      {
        path: 'insights/overview',
        name: 'insights-overview',
        component: () => import('@/views/InsightsView.vue'),
      },
      {
        path: 'insights/readiness',
        name: 'insights-readiness',
        component: () => import('@/views/InsightsView.vue'),
      },
      {
        path: 'insights/reviews',
        name: 'insights-reviews',
        component: () => import('@/views/InsightsView.vue'),
      },
      {
        path: 'knowledge-graph',
        name: 'knowledge-graph',
        redirect: to => ({ name: 'insights-readiness', query: { ...to.query, view: 'graph' } }),
      },
      {
        path: 'import',
        name: 'import',
        component: () => import('@/views/ImportView.vue'),
      },
      {
        path: 'coding',
        name: 'coding',
        component: () => import('@/views/CodingView.vue'),
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
      },
      {
        path: 'resume',
        name: 'resume',
        component: () => import('@/views/ResumeView.vue'),
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 认证守卫 — 等待 initAuth 完成后再判断
router.beforeEach(async (to) => {
  // 等待 App.vue 的 initAuth() 完成
  if (!authInitialized) {
    await authReady
  }

  if (to.matched.some(record => record.meta.requiresAuth)) {
    if (to.query.preview === '1') return true
    if (!currentUser.value) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  if (to.name === 'login' && currentUser.value) {
    return { name: 'master-bank' }
  }
})

export default router

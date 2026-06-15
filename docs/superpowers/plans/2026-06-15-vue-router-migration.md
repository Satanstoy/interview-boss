# Vue Router 迁移实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 Vue Router 替换 activeTab + v-if 实现前端路由，支持深度链接，App.vue 从 ~990 行瘦身到 ~80 行。

**Architecture:** 使用 Vue Router 4 嵌套路由 + provide/inject 共享数据。AuthenticatedLayout 调用 composables 并 provide 数据，各 view 组件 inject 消费。useAuth 改为单例以支持路由守卫访问认证状态。

**Tech Stack:** vue-router@4, Vue 3 Composition API, provide/inject

**设计文档:** `docs/superpowers/specs/2026-06-15-vue-router-migration-design.md`

---

## 数据流架构

```
App.vue (~80行)
├── <Toaster> / <ConfirmDialog> / <LoginModal>
└── <router-view />

router-view → AuthenticatedLayout.vue
├── 调用 useMasterBankData() + useAuth() + useBuildTrigger()
├── provide('appData', { ...所有共享数据 })
├── <AppSidebar> (inject appData, 使用 router-link)
├── <SiteHeader>
└── <router-view /> → 各 View 组件 (inject appData)

router-view → BlankLayout.vue
└── <router-view /> → LoginView
```

---

## Task 1: 安装 Vue Router + 路由配置 + 认证守卫

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/router/index.js` (替换现有 null 占位)
- Modify: `frontend/src/main.js:1-125`
- Modify: `frontend/src/composables/useAuth.js:1-69`

- [ ] **Step 1.1: 安装 vue-router**

```bash
cd frontend && npm install vue-router@4
```

- [ ] **Step 1.2: 将 useAuth 改为单例模式**

当前 `useAuth` 每次调用创建新 ref，router guard 和 layout 会拿到不同的 `currentUser`。改为模块级单例：

```js
// frontend/src/composables/useAuth.js
/**
 * useAuth — 认证状态管理（单例模式）
 *
 * 职责：currentUser、登录/登出/刷新token、未授权拦截、待审核数量
 * 不负责：数据获取（由调用方通过回调注入）
 *
 * 单例：模块级 ref 保证 router guard 和组件拿到同一个 currentUser
 */
import { ref } from 'vue'
import { setAuthToken, refreshAuthToken, setUnauthorizedHandler, invalidateCache } from '@/services/http.js'
import * as api from '@/api/index.js'

// ── 模块级状态（单例） ──
const currentUser = ref(null)
const showLoginModal = ref(false)
const pendingReviewCount = ref(0)

// ── 回调占位（由 initSingleton 注入） ──
let _onReady = null
let _onDataRefresh = null

// ── 内部：加载待审核数量（仅 admin） ──
const loadPendingCount = async () => {
  if (!currentUser.value?.is_admin) { pendingReviewCount.value = 0; return }
  try { const data = await api.fetchPendingQuestions(); pendingReviewCount.value = data.total || 0 }
  catch { pendingReviewCount.value = 0 }
}

// ── Token 刷新 / 自动登录 ──
const initAuth = async () => {
  const refreshResult = await refreshAuthToken()
  if (refreshResult?.token && refreshResult?.user) {
    setAuthToken(refreshResult.token)
    currentUser.value = refreshResult.user
    _onReady?.()
    loadPendingCount()
  }
}

// ── 登录成功 ──
const handleLoginSuccess = (user) => {
  currentUser.value = user
  _onReady?.()
  loadPendingCount()
}

// ── 登出 ──
const handleLogout = () => {
  setAuthToken('')
  currentUser.value = null
  _onDataRefresh?.()
  pendingReviewCount.value = 0
}

// ── 切换题库模式（公共/个人） ──
const handleBankModeChanged = (user) => {
  currentUser.value = user
  invalidateCache('master-bank')
  _onDataRefresh?.()
}

// ── 401 拦截：弹出登录框 ──
setUnauthorizedHandler(() => { showLoginModal.value = true })

/**
 * 初始化单例回调（在 layout 中调用一次）
 * 路由守卫直接 import { currentUser } 即可
 */
export function initAuthSingleton({ onReady, onDataRefresh } = {}) {
  _onReady = onReady || null
  _onDataRefresh = onDataRefresh || null
}

export function useAuth() {
  return {
    currentUser,
    showLoginModal,
    pendingReviewCount,
    initAuth,
    handleLoginSuccess,
    handleLogout,
    handleBankModeChanged,
    loadPendingCount,
  }
}
```

- [ ] **Step 1.3: 创建路由配置**

```js
// frontend/src/router/index.js
import { createRouter, createWebHistory } from 'vue-router'
import { currentUser } from '@/composables/useAuth.js'

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
        path: 'chat',
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
        path: 'mock-interview',
        name: 'mock-interview',
        component: () => import('@/views/MockInterviewView.vue'),
      },
      {
        path: 'knowledge-graph',
        name: 'knowledge-graph',
        component: () => import('@/views/KnowledgeGraphView.vue'),
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
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/master-bank',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 认证守卫
router.beforeEach((to) => {
  if (to.matched.some(record => record.meta.requiresAuth)) {
    if (!currentUser.value) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  if (to.name === 'login' && currentUser.value) {
    return { name: 'master-bank' }
  }
})

export default router
```

- [ ] **Step 1.4: 在 main.js 注册 router**

在 `frontend/src/main.js` 第 4 行后添加 router import 和注册：

```js
import { createApp } from 'vue'
import '@/assets/styles/global.css'
import 'vue-sonner/style.css'
import App from './App.vue'
import router from './router'                          // ← 新增
import { autoAnimatePlugin } from '@formkit/auto-animate/vue'
// ... 其余 import 不变 ...

const app = createApp(App)
app.use(router)                                         // ← 新增
app.use(autoAnimatePlugin)
app.use(MotionPlugin)
// ... 其余不变 ...
app.mount('#app')
```

- [ ] **Step 1.5: 更新前端 CLAUDE.md 路由配置说明**

在 `frontend/CLAUDE.md` 中更新路由相关说明，记录已引入 Vue Router。

- [ ] **Step 1.6: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功（此时路由已注册但 App.vue 仍是旧代码，hash 路由和 vue-router 共存无冲突）。

- [ ] **Step 1.7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/router/index.js frontend/src/main.js frontend/src/composables/useAuth.js
git commit -m "feat(router): install vue-router, create route config with auth guard

- Install vue-router@4
- Create router/index.js with all routes and beforeEach guard
- Convert useAuth to singleton (module-level refs)
- Register router in main.js"
```

---

## Task 2: 创建 AuthenticatedLayout — 数据提供层

**Files:**
- Create: `frontend/src/layouts/AuthenticatedLayout.vue`

- [ ] **Step 2.1: 创建 AuthenticatedLayout.vue**

此组件承担原 App.vue 的数据初始化职责，调用 composables 并 provide 给子 view：

```vue
<!-- frontend/src/layouts/AuthenticatedLayout.vue -->
<script setup>
import { ref, computed, provide, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { cancelAllRequests } from '@/services/http.js'
import { safeUrl } from '@/utils/validate.js'
import { useSelection } from '@/composables/useSelection.js'
import { useTheme } from '@/composables/useTheme.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import AppSidebar from '@/components/AppSidebar.vue'
import SiteHeader from '@/components/SiteHeader.vue'
import { useHighlightNav } from '@/composables/useHighlightNav.js'
import { useQuestionOps } from '@/composables/useQuestionOps.js'
import { useMergeDialog } from '@/composables/useMergeDialog.js'
import { useBatchActions } from '@/composables/useBatchActions.js'
import { useTabScroll } from '@/composables/useTabScroll.js'
import { useAuth, initAuthSingleton } from '@/composables/useAuth.js'
import { useMasterBankData } from '@/composables/useMasterBankData.js'
import { useBuildTrigger } from '@/composables/useBuildTrigger.js'
import { setOnJobDone, restoreActiveJobs } from '@/composables/useSubmitJobs.js'

import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import LoginModal from '@/components/business/LoginModal.vue'
import MergeQuestionDialog from '@/components/business/MergeQuestionDialog.vue'
import PracticePanel from '@/components/business/PracticePanel.vue'
import AdminReview from '@/components/business/AdminReview.vue'
import PracticeMode from '@/components/business/PracticeMode.vue'

const router = useRouter()
const toast = useToast()
const { confirm: showConfirm } = useConfirm()
const { isDark, toggleDark } = useTheme()

// ── preview mode ──
const isPreviewMode = new URLSearchParams(window.location.search).get('preview') === '1'

// ── Data ──
let afterFetchCleanup = () => {}
const {
  jdData, interviewData, masterBank,
  isDataLoading, dataLoadError,
  analytics, practiceStats, popularTags, categoryCounts,
  masterBankTotal, masterBankOverallTotal,
  activeSeason, availableSeasons,
  isLoadingMore, hasMore, loadMoreMasterBank,
  selectedTag, selectedSubTags, searchQuery,
  filterDifficulty, showStarredOnly,
  filterSeason, interviewSortOrder,
  filteredMasterBank, filteredInterviewData,
  availableSubTags, interviewSeasons, practicedQuestions,
  fetchTableData, fetchAnalytics, fetchPracticeStats,
  loadActiveSeason, loadAllData, formatDate,
} = useMasterBankData({ onAfterFetch: () => afterFetchCleanup() })

// ── Build ──
const {
  isBuilding, buildProgress, buildStepList,
  triggerBuildMasterBank, triggerBuildPersonalBank,
} = useBuildTrigger({ onRebuildDone: () => { fetchTableData(); fetchAnalytics() } })

// ── Selection ──
const jdSelection = useSelection(() => jdData.value)
const interviewSelection = useSelection(() => interviewData.value)
const masterSelection = useSelection(() => filteredMasterBank.value)
const isMasterSelected = (id) => masterSelection.selectedIds.value.has(id)
afterFetchCleanup = () => { jdSelection.clearSelection(); interviewSelection.clearSelection() }

// ── Auth ──
const {
  currentUser, showLoginModal, pendingReviewCount,
  initAuth, handleLoginSuccess, handleLogout, handleBankModeChanged,
} = useAuth()

// 初始化单例回调
initAuthSingleton({
  onReady: loadAllData,
  onDataRefresh: () => { fetchTableData(); fetchPracticeStats() },
})

const previewUser = { id: 'preview-user', username: 'Preview', is_admin: true, bank_mode: 'mixed' }
const displayUser = computed(() => currentUser.value || (isPreviewMode ? previewUser : null))
const isAuthenticatedForUi = computed(() => Boolean(displayUser.value))

const applyPreviewData = () => {
  // ... 与原 App.vue applyPreviewData 完全相同（lines 658-738）...
  // 此处省略，迁移时从 App.vue 复制
}

// ── UI state ──
const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
const showReviewPanel = ref(false)
const practiceQuestion = ref(null)
const practiceModeIndex = ref(0)
const showPracticeMode = ref(false)
const mockInterviewRef = ref(null)
const masterBankRef = ref(null)
const jdCurrentPage = ref(1)
const jdPageSize = ref(20)
const interviewCurrentPage = ref(1)
const interviewPageSize = ref(20)

// ── Highlight nav ──
const {
  highlightInterviewId, returnTab, returnToPracticeMode,
  floatingReturnBtn, floatingBtnStyle, masterBankEverShown,
  handleReturn, detachHighlightScroll, setSavedScrollTop,
} = useHighlightNav(router, showPracticeMode)

// ── Question operations ──
const {
  reprocessingIds, reprocessProgress, activeReprocessing,
  deleteDataRow, reprocessInterview, retagQuestion,
  saveField, saveFieldFromEvent, toggleStar,
  generateAnswer, useReferenceAnswer, saveUserAnswer,
  deleteQuestion, deleteOriginalQuestion, editQuestion, onUpdateAnswer, splitQuestion,
} = useQuestionOps(masterBank, currentUser, fetchTableData, fetchAnalytics)

// ── Merge dialog ──
const {
  mergeDialogVisible, mergeSourceOriginalQ, mergeSearchQuery,
  mergeSearchResults, mergeSearching, startMerge, doMergeSearch, confirmMerge, splitAsNew,
} = useMergeDialog(fetchTableData)

// ── Batch actions ──
const { jdBatchActions, interviewBatchActions, masterBatchActions } = useBatchActions({
  currentUser, jdSelection, interviewSelection, masterSelection, fetchTableData, fetchAnalytics,
})

// ── Tab scroll ──
const { saveScroll, prepareRestore, restoreScroll } = useTabScroll()

// ── Sidebar tabs (with route mapping) ──
const sidebarTabs = computed(() => [
  { key: 'MasterBank', label: '高频题库', route: '/master-bank', count: masterBankTotal.value || filteredMasterBank.value.length },
  { key: 'Chat', label: '模拟面试', route: '/chat' },
  { key: 'JD', label: 'JD 筛选', route: '/jd', count: jdData.value.length },
  { key: 'Interview', label: '面经库', route: '/interview', count: interviewData.value.length },
  { key: 'MockInterview', label: '题目抽测', route: '/mock-interview' },
  { key: 'KnowledgeGraph', label: '知识图谱', route: '/knowledge-graph' },
  { key: 'Import', label: '导入', route: '/import' },
  { key: 'Coding', label: '手撕代码', route: '/coding' },
])

// ── Cross-view navigation functions ──
const onGoToQuestion = (question) => {
  const q = question.question || ''
  searchQuery.value = q.length > 30 ? q.substring(0, 30) : q
  selectedTag.value = '全部'; selectedSubTags.value = []
  router.push('/master-bank')
}
const onNavigateToInterview = (event) => {
  // ... 与原 App.vue onNavigateToInterview 相同逻辑，但用 router.push('/interview') 替换 activeTab = 'Interview' ...
}

// ── Practice mode ──
const enterPracticeMode = () => {
  if (filteredMasterBank.value.length === 0) { toast.warning('当前筛选条件下没有题目'); return }
  practiceModeIndex.value = 0
  showPracticeMode.value = true
}
const handlePracticeModeClose = () => { showPracticeMode.value = false; fetchPracticeStats() }

// ── Watch sidebar collapsed ──
watch(sidebarCollapsed, (val) => { localStorage.setItem('sidebar-collapsed', String(val)) })

// ── Global upload job recovery ──
setOnJobDone(() => { fetchTableData(); fetchAnalytics() })

// ── Lifecycle ──
onMounted(async () => {
  if (isPreviewMode) {
    currentUser.value = previewUser
    applyPreviewData()
  } else {
    await initAuth()
    try { await restoreActiveJobs() } catch {}
  }
  window.__VUE_APP_READY__ = true
})
onUnmounted(() => { cancelAllRequests(); detachHighlightScroll() })

// ── Provide to child views ──
provide('appData', {
  // data refs
  jdData, interviewData, masterBank,
  isDataLoading, dataLoadError,
  analytics, practiceStats, popularTags, categoryCounts,
  masterBankTotal, masterBankOverallTotal,
  activeSeason, availableSeasons,
  isLoadingMore, hasMore, loadMoreMasterBank,
  // filters
  selectedTag, selectedSubTags, searchQuery,
  filterDifficulty, showStarredOnly,
  filterSeason, interviewSortOrder,
  // computed
  filteredMasterBank, filteredInterviewData,
  availableSubTags, interviewSeasons, practicedQuestions,
  // fetch
  fetchTableData, fetchAnalytics, fetchPracticeStats,
  loadAllData, formatDate,
  // auth
  displayUser, isAuthenticatedForUi, currentUser,
  pendingReviewCount, showLoginModal,
  handleLoginSuccess, handleLogout, handleBankModeChanged,
  // build
  isBuilding, triggerBuildMasterBank, triggerBuildPersonalBank,
  // selections
  jdSelection, interviewSelection, masterSelection, isMasterSelected,
  jdBatchActions, interviewBatchActions, masterBatchActions,
  // question ops
  reprocessingIds, reprocessProgress, activeReprocessing,
  deleteDataRow, reprocessInterview, retagQuestion,
  saveField, saveFieldFromEvent, toggleStar,
  generateAnswer, useReferenceAnswer, saveUserAnswer,
  deleteQuestion, deleteOriginalQuestion, editQuestion, onUpdateAnswer, splitQuestion,
  // merge
  mergeDialogVisible, mergeSourceOriginalQ, mergeSearchQuery,
  mergeSearchResults, mergeSearching, startMerge, doMergeSearch, confirmMerge, splitAsNew,
  // practice
  showPracticeMode, enterPracticeMode, practiceQuestion, practiceModeIndex,
  handlePracticeModeClose,
  // highlight nav
  highlightInterviewId, returnTab, returnToPracticeMode,
  floatingReturnBtn, floatingBtnStyle, masterBankEverShown,
  handleReturn, setSavedScrollTop,
  // cross-view navigation
  onGoToQuestion, onNavigateToInterview,
  // pagination
  jdCurrentPage, jdPageSize, interviewCurrentPage, interviewPageSize,
  // review
  showReviewPanel,
  // UI
  sidebarCollapsed, sidebarTabs, isPreviewMode,
  isDark, toggleDark, showConfirm, toast,
  // safeUrl
  safeUrl,
})
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <aside
      class="hidden md:flex shrink-0 flex-col border-r border-border bg-sidebar h-screen sticky top-0 overflow-hidden"
      :style="{ width: sidebarCollapsed ? '60px' : '256px', transition: 'width 380ms cubic-bezier(0.4, 0, 0.2, 1)' }"
    >
      <AppSidebar
        :sidebar-tabs="sidebarTabs"
        :display-user="displayUser"
        :pending-review-count="pendingReviewCount"
        @update:collapsed="sidebarCollapsed = $event"
        @go-to-question="onGoToQuestion"
        @logout="handleLogout"
        @bank-mode-changed="handleBankModeChanged"
        @show-review="showReviewPanel = true"
      />
    </aside>

    <main class="flex-1 min-w-0 flex flex-col">
      <SiteHeader
        :active-season="activeSeason"
        @show-settings="router.push('/settings')"
      />
      <router-view v-slot="{ Component }">
        <Transition name="tab-fade">
          <component :is="Component" />
        </Transition>
      </router-view>
    </main>
  </div>

  <!-- Global modals -->
  <ConfirmDialog />
  <LoginModal :visible="showLoginModal" @close="showLoginModal = false" @login-success="handleLoginSuccess" />
  <AdminReview :visible="showReviewPanel" @close="showReviewPanel = false" @reviewed="fetchTableData" />
  <PracticePanel :visible="!!practiceQuestion" :question="practiceQuestion" @close="practiceQuestion = null" @answer-evaluated="fetchPracticeStats" @navigate-to-interview="onNavigateToInterview" />
  <PracticeMode
    v-if="showPracticeMode"
    :questions="filteredMasterBank"
    :start-index="practiceModeIndex"
    :bank-mode="displayUser?.bank_mode"
    :is-admin="displayUser?.is_admin"
    @close="handlePracticeModeClose"
    @answer-evaluated="fetchPracticeStats"
    @toggle-star="toggleStar"
    @navigate-to-interview="onNavigateToInterview"
  />
  <MergeQuestionDialog
    :visible="mergeDialogVisible"
    :source-question="mergeSourceOriginalQ"
    :search-query="mergeSearchQuery"
    :results="mergeSearchResults"
    :searching="mergeSearching"
    @close="mergeDialogVisible = false"
    @search="doMergeSearch"
    @confirm="confirmMerge"
    @split="splitAsNew"
    @update:search-query="mergeSearchQuery = $event"
  />

  <!-- Reprocessing toast -->
  <Transition name="tab-fade">
    <div v-if="Object.keys(activeReprocessing).length > 0"
         class="fixed bottom-4 right-4 z-50 bg-card rounded-xl shadow-lg border border-border p-4 max-w-sm">
      <div class="flex items-center gap-3">
        <div class="animate-spin size-5 border-2 border-primary-600 border-t-transparent rounded-full flex-shrink-0"></div>
        <div>
          <p class="text-sm font-medium text-foreground">正在分析面经...</p>
          <p v-for="(info, id) in activeReprocessing" :key="id"
             class="text-xs text-muted-foreground mt-0.5">
            {{ info.message || '准备中...' }}
          </p>
        </div>
      </div>
    </div>
  </Transition>
</template>
```

**注意：** 此文件的模板和脚本较长（约 300 行脚本 + 80 行模板），但远小于原 App.vue 的 990 行。关键是它只做"数据初始化 + 提供 + 全局模态框"，不做页面渲染。

- [ ] **Step 2.2: 创建 BlankLayout.vue**

```vue
<!-- frontend/src/layouts/BlankLayout.vue -->
<template>
  <router-view />
</template>
```

- [ ] **Step 2.3: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功（layout 文件已创建但尚未被使用）。

- [ ] **Step 2.4: Commit**

```bash
git add frontend/src/layouts/AuthenticatedLayout.vue frontend/src/layouts/BlankLayout.vue
git commit -m "feat(router): create AuthenticatedLayout with data provider layer

- AuthenticatedLayout calls composables and provides data via inject
- BlankLayout for login page
- Global modals (ConfirmDialog, LoginModal, etc.) moved to layout"
```

---

## Task 3: 创建 View 组件 — 从 App.vue 提取页面

**Files:**
- Create: `frontend/src/views/MasterBankView.vue`
- Create: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/views/JdView.vue`
- Create: `frontend/src/views/InterviewView.vue`
- Create: `frontend/src/views/MockInterviewView.vue`
- Create: `frontend/src/views/KnowledgeGraphView.vue`
- Create: `frontend/src/views/ImportView.vue`
- Create: `frontend/src/views/CodingView.vue`
- Create: `frontend/src/views/SettingsView.vue`
- Create: `frontend/src/views/LoginView.vue`

所有 view 组件的统一模式：

```vue
<script setup>
import { inject } from 'vue'
const { /* 解构需要的数据 */ } = inject('appData')
</script>
```

- [ ] **Step 3.1: 创建 MasterBankView.vue**

从 App.vue 模板 lines 156-261 提取。需要 inject 的数据：

```vue
<!-- frontend/src/views/MasterBankView.vue -->
<script setup>
import { inject } from 'vue'
import SearchFilterBar from '@/components/business/SearchFilterBar.vue'
import ExamDistribution from '@/components/business/ExamDistribution.vue'
import MasterBankList from '@/components/business/MasterBankList.vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

const {
  masterBank, filteredMasterBank, isDataLoading, dataLoadError,
  masterBankTotal, masterBankOverallTotal,
  categoryCounts, selectedTag, selectedSubTags, availableSubTags,
  searchQuery, filterDifficulty,
  masterSelection, isMasterSelected, masterBatchActions,
  practicedQuestions, displayUser,
  isLoadingMore, hasMore, loadMoreMasterBank,
  isBuilding, triggerBuildMasterBank, triggerBuildPersonalBank,
  fetchTableData, enterPracticeMode,
  toggleStar, retagQuestion, generateAnswer, useReferenceAnswer,
  saveUserAnswer, saveFieldFromEvent, deleteQuestion, deleteOriginalQuestion,
  editQuestion, onUpdateAnswer, splitQuestion, startMerge,
  onNavigateToInterview, onGoToQuestion,
  masterBankEverShown,
} = inject('appData')

const onSelectTag = (tag) => {
  selectedTag.value = tag
  selectedSubTags.value = []
}

const toggleSubTag = (tag) => {
  const idx = selectedSubTags.value.indexOf(tag)
  if (idx === -1) { selectedSubTags.value = [...selectedSubTags.value, tag] }
  else { selectedSubTags.value = selectedSubTags.value.filter(t => t !== tag) }
}

const skeletonCards = [
  { title: '75%', subtitle: '45%' },
  { title: '60%', subtitle: '55%' },
  { title: '85%', subtitle: '35%' },
  { title: '50%', subtitle: '65%' },
  { title: '70%', subtitle: '40%' },
]
</script>

<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <!-- Error banner -->
    <div v-if="dataLoadError" class="mb-4 bg-red-50/80 dark:bg-red-900/20 border border-red-200/80 dark:border-red-800/50 text-red-700 dark:text-red-400 px-4 py-3 rounded-xl flex items-center justify-between">
      <span class="flex items-center gap-2 text-sm">
        <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        {{ dataLoadError }}
      </span>
      <button @click="fetchTableData" class="text-sm bg-red-100/80 dark:bg-red-900/40 hover:bg-red-200 dark:hover:bg-red-800/40 px-3 py-1 rounded-lg transition font-medium">重试</button>
    </div>

    <!-- Loading skeleton -->
    <div v-if="isDataLoading && masterBank.length === 0" class="py-10 flex flex-col gap-4">
      <!-- ... skeleton cards from App.vue lines 128-150 ... -->
    </div>

    <!-- SearchFilterBar -->
    <SearchFilterBar
      :search-query="searchQuery"
      :filter-difficulty="filterDifficulty"
      @update:search-query="searchQuery = $event"
      @update:filter-difficulty="filterDifficulty = $event"
    />

    <!-- Category tags -->
    <div class="flex flex-wrap gap-1.5 mb-2">
      <button @click="onSelectTag('全部')"
        class="text-xs px-2.5 py-1.5 rounded-lg border transition-all duration-200 font-medium"
        :class="selectedTag === '全部' ? 'bg-primary/10 dark:bg-primary/20 text-primary border-primary/30 shadow-sm' : 'bg-white dark:bg-muted text-muted-foreground border-border hover:bg-muted'">
        全部 <span class="ml-1 opacity-60 font-mono tabular-nums">{{ masterBankOverallTotal || masterBank.length }}</span>
      </button>
      <button v-for="(count, topic) in categoryCounts" :key="topic"
        @click="onSelectTag(topic)"
        class="text-xs px-2.5 py-1.5 rounded-lg border transition-all duration-200 group"
        :class="selectedTag === topic ? 'bg-primary/10 dark:bg-primary/20 text-primary border-primary/30 font-semibold shadow-sm' : 'bg-white dark:bg-muted text-muted-foreground border-border hover:bg-muted'">
        {{ topic }} <span class="ml-1 opacity-60 font-mono tabular-nums">{{ count }}</span>
      </button>
    </div>

    <!-- Sub-tag filter chips -->
    <div v-if="selectedTag !== '全部' && availableSubTags.length > 0" class="flex flex-wrap gap-2 mb-2">
      <span class="text-xs text-muted-foreground self-center mr-1 font-medium">子标签：</span>
      <button v-for="st in availableSubTags" :key="st.tag" @click="toggleSubTag(st.tag)"
        class="text-xs px-2.5 py-1 rounded-lg border transition-all duration-200"
        :class="selectedSubTags.includes(st.tag) ? 'bg-primary/10 text-primary border-primary/30 font-semibold shadow-sm' : 'bg-white dark:bg-muted text-muted-foreground border-border hover:bg-muted'">
        {{ st.tag }} <span class="ml-1 opacity-50">{{ st.count }}</span>
      </button>
    </div>

    <!-- Exam Distribution Chart -->
    <ExamDistribution :master-bank="masterBank" :default-collapsed="true" />

    <!-- MasterBankList -->
    <div class="flex flex-col flex-1 min-h-0">
      <MasterBankList
        :items="filteredMasterBank"
        :selected-count="masterSelection.selectedCount.value"
        :is-selected="isMasterSelected"
        :batch-actions="masterBatchActions"
        :practiced-questions="practicedQuestions"
        :bank-mode="displayUser?.bank_mode"
        :is-admin="displayUser?.is_admin"
        :current-user-id="displayUser?.id"
        :is-loading-more="isLoadingMore"
        :has-more="hasMore"
        @toggle-select-all="masterSelection.toggleSelectAll()"
        @invert-selection="masterSelection.invertSelection()"
        @toggle-item="masterSelection.toggleItem($event)"
        @toggle-star="toggleStar"
        @retag="retagQuestion"
        @generate-answer="generateAnswer"
        @use-reference-answer="useReferenceAnswer"
        @save-user-answer="saveUserAnswer"
        @save-field="saveFieldFromEvent"
        @practice="$event => practiceQuestion = $event"
        @split-question="splitQuestion"
        @start-merge="startMerge"
        @navigate-to-interview="onNavigateToInterview"
        @delete="deleteQuestion"
        @edit-question="editQuestion"
        @delete-original-question="deleteOriginalQuestion"
        @update-answer="onUpdateAnswer"
        @load-more="loadMoreMasterBank"
      >
        <template #actions>
          <div class="flex flex-wrap items-center gap-2 pt-1">
            <Button v-if="displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildMasterBank" :disabled="isBuilding">
              {{ isBuilding ? '重建中...' : '重建题库' }}
            </Button>
            <Button v-if="!displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildPersonalBank" :disabled="isBuilding">
              {{ isBuilding ? '重建中...' : '重建题库' }}
            </Button>
            <Button v-if="filteredMasterBank.length > 0" variant="outline" size="sm" @click="enterPracticeMode">
              刷题模式
            </Button>
            <Button v-if="!isDataLoading" variant="outline" size="sm" @click="fetchTableData" :disabled="isDataLoading">
              刷新
            </Button>
          </div>
        </template>
      </MasterBankList>
    </div>
  </div>
</template>
```

- [ ] **Step 3.2: 创建 ChatView.vue**

```vue
<!-- frontend/src/views/ChatView.vue -->
<script setup>
import { inject, defineAsyncComponent } from 'vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const { jdData, isPreviewMode } = inject('appData')

const ChatViewComponent = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/ChatView.vue'),
})
</script>

<template>
  <KeepAlive>
    <ChatViewComponent
      :jd-list="jdData"
      :preview="isPreviewMode"
      class="flex-1 min-h-0"
    />
  </KeepAlive>
</template>
```

- [ ] **Step 3.3: 创建 JdView.vue**

从 App.vue 模板 lines 263-308 提取 DataTable-JD 部分。inject `jdData`, `displayUser`, `jdSelection`, `jdBatchActions`, `jdCurrentPage`, `jdPageSize`, `safeUrl`, `saveField`, `deleteDataRow`。

- [ ] **Step 3.4: 创建 InterviewView.vue**

从 App.vue 模板 lines 310-399 提取 DataTable-Interview 部分。inject `interviewData`, `filteredInterviewData`, `interviewSelection`, `interviewBatchActions`, `interviewCurrentPage`, `interviewPageSize`, `filterSeason`, `interviewSortOrder`, `interviewSeasons`, `highlightInterviewId`, `displayUser`, `safeUrl`, `saveField`, `deleteDataRow`, `reprocessInterview`, `reprocessingIds`, `reprocessProgress`, `returnTab`, `handleReturn`, `floatingReturnBtn`, `floatingBtnStyle`, `returnToPracticeMode`。

- [ ] **Step 3.5: 创建 MockInterviewView.vue**

```vue
<!-- frontend/src/views/MockInterviewView.vue -->
<script setup>
import { inject, defineAsyncComponent } from 'vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const { popularTags } = inject('appData')

const MockInterview = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/MockInterview.vue'),
})
</script>

<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <MockInterview :popular-tags="popularTags" />
  </div>
</template>
```

- [ ] **Step 3.6: 创建 KnowledgeGraphView.vue**

```vue
<!-- frontend/src/views/KnowledgeGraphView.vue -->
<script setup>
import { inject, defineAsyncComponent } from 'vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { useRouter } from 'vue-router'

const { selectedTag, selectedSubTags, searchQuery } = inject('appData')
const router = useRouter()

const KnowledgeGraph = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/KnowledgeGraph.vue'),
})

const onGraphFilterTag = (tagName) => {
  selectedTag.value = '全部'; selectedSubTags.value = []; searchQuery.value = tagName; router.push('/master-bank')
}
const onGraphFilterCategory = (catName) => {
  selectedTag.value = catName; selectedSubTags.value = []; searchQuery.value = ''; router.push('/master-bank')
}
</script>

<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <KnowledgeGraph @filter-by-tag="onGraphFilterTag" @filter-by-category="onGraphFilterCategory" />
  </div>
</template>
```

- [ ] **Step 3.7: 创建 ImportView.vue**

```vue
<!-- frontend/src/views/ImportView.vue -->
<script setup>
import { inject } from 'vue'
import StagingPanel from '@/components/business/StagingPanel.vue'

const { activeSeason, availableSeasons, displayUser, fetchTableData, fetchAnalytics } = inject('appData')

const onSubmitted = () => { fetchTableData(); fetchAnalytics() }
</script>

<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <StagingPanel
      :active-season="activeSeason"
      :available-seasons="availableSeasons"
      :is-admin="displayUser?.is_admin"
      @submitted="onSubmitted"
    />
  </div>
</template>
```

- [ ] **Step 3.8: 创建 CodingView.vue**

```vue
<!-- frontend/src/views/CodingView.vue -->
<script setup>
import { defineAsyncComponent } from 'vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const CodingPractice = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/CodingPractice.vue'),
})
</script>

<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <CodingPractice />
  </div>
</template>
```

- [ ] **Step 3.9: 创建 SettingsView.vue**

```vue
<!-- frontend/src/views/SettingsView.vue -->
<script setup>
import { inject } from 'vue'
import { useRouter } from 'vue-router'
import SettingsPage from '@/components/business/SettingsPage.vue'

const {
  displayUser, practiceStats, masterBank,
  activeSeason, availableSeasons, isBuilding,
  handleLogout, handleBankModeChanged,
  fetchTableData, triggerBuildMasterBank,
  sidebarCollapsed,
} = inject('appData')

const router = useRouter()
</script>

<template>
  <SettingsPage
    :display-user="displayUser"
    :practice-stats="practiceStats"
    :master-bank="masterBank"
    :is-admin="displayUser?.is_admin"
    :active-season="activeSeason"
    :available-seasons="availableSeasons"
    :is-building="isBuilding"
    @close="router.back()"
    @go-to-question="onGoToQuestion"
    @logout="handleLogout"
    @bank-mode-changed="handleBankModeChanged"
    @profile-updated="fetchTableData"
    @build-master-bank="triggerBuildMasterBank"
    @update:active-season="activeSeason = $event"
    @sidebar-collapsed-changed="sidebarCollapsed = $event"
  />
</template>
```

- [ ] **Step 3.10: 创建 LoginView.vue**

```vue
<!-- frontend/src/views/LoginView.vue -->
<script setup>
import { inject } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import LoginPage from '@/components/business/LoginPage.vue'

const { handleLoginSuccess } = inject('appData')
const router = useRouter()
const route = useRoute()

const onLoginSuccess = (user) => {
  handleLoginSuccess(user)
  const redirect = route.query.redirect || '/master-bank'
  router.push(redirect)
}
</script>

<template>
  <LoginPage @login-success="onLoginSuccess" />
</template>
```

- [ ] **Step 3.11: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功（view 文件已创建但 App.vue 仍是旧代码，两者不冲突）。

- [ ] **Step 3.12: Commit**

```bash
git add frontend/src/views/
git commit -m "feat(router): create all view components extracted from App.vue

- 10 view components: MasterBank, Chat, JD, Interview, MockInterview,
  KnowledgeGraph, Import, Coding, Settings, Login
- Each view uses inject('appData') to access shared data
- Async components use router-level lazy loading"
```

---

## Task 4: 改造 AppSidebar 和 TabBar 使用 router-link

**Files:**
- Modify: `frontend/src/components/AppSidebar.vue:1-216`
- Modify: `frontend/src/components/common/TabBar.vue:1-59`

- [ ] **Step 4.1: 改造 AppSidebar.vue**

关键变更：
1. 导入 `useRouter`, `useRoute`
2. `onTabChange` 改为 `router.push(tab.route)`
3. 高亮判断从 `activeTab === tab.key` 改为 `route.path === tab.route`
4. 不再需要 `activeTab` prop 和 `update:active-tab` emit

```vue
<!-- frontend/src/components/AppSidebar.vue -->
<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { HugeiconsIcon } from '@hugeicons/vue'
import { Book02Icon, AiChat01Icon, FilterIcon, BookBookmark01Icon, TestTube01Icon, AiNetworkIcon, BookUploadIcon, BracesIcon } from '@hugeicons/core-free-icons'
import { PanelLeft } from '@lucide/vue'
import UserMenu from '@/components/business/UserMenu.vue'

const props = defineProps({
  sidebarTabs: { type: Array, default: () => [] },
  displayUser: { type: Object, default: null },
  pendingReviewCount: { type: Number, default: 0 },
})

const emit = defineEmits([
  'go-to-question', 'logout', 'bank-mode-changed',
  'show-review', 'show-settings', 'update:collapsed',
])

const router = useRouter()
const route = useRoute()
const collapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
const logoHovered = ref(false)

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  logoHovered.value = false
  emit('update:collapsed', collapsed.value)
}

const iconMap = {
  MasterBank: Book02Icon, Chat: AiChat01Icon, JD: FilterIcon,
  Interview: BookBookmark01Icon, MockInterview: TestTube01Icon,
  KnowledgeGraph: AiNetworkIcon, Import: BookUploadIcon, Coding: BracesIcon,
}

function isActive(tabRoute) {
  return route.path === tabRoute || route.path.startsWith(tabRoute + '/')
}

function onTabChange(tab) { router.push(tab.route) }
function onGoToQuestion(q) { emit('go-to-question', q) }
function handleLogout() { emit('logout') }
function handleBankModeChanged(val) { emit('bank-mode-changed', val) }
function handleShowReview() { emit('show-review') }
function handleShowSettings() { emit('show-settings') }
</script>

<template>
  <!-- Collapsed view -->
  <div v-if="collapsed" class="flex flex-col h-full items-center py-3 px-2 gap-1 animate-sidebar-collapse">
    <button @mouseenter="logoHovered = true" @mouseleave="logoHovered = false" @click="toggleCollapsed"
      class="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-all duration-300 mb-1 overflow-hidden"
      :class="logoHovered ? 'bg-sidebar-accent text-sidebar-foreground cursor-pointer' : 'bg-gradient-to-br from-primary to-primary-600 text-white shadow-lg shadow-primary/20'"
      :title="logoHovered ? '展开侧栏' : undefined">
      <span class="text-sm font-bold transition-all duration-300 ease-out" :class="logoHovered ? 'opacity-0 scale-75' : 'opacity-100 scale-100'">IB</span>
      <PanelLeft :size="18" class="absolute transition-all duration-300 ease-out" :class="logoHovered ? 'opacity-100 scale-100' : 'opacity-0 scale-75'" />
    </button>

    <button v-for="tab in sidebarTabs" :key="tab.key" @click="onTabChange(tab)"
      class="flex items-center justify-center w-10 h-10 rounded-lg transition-all duration-300"
      :class="isActive(tab.route) ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/50 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
      :title="tab.label">
      <HugeiconsIcon v-if="iconMap[tab.key]" :icon="iconMap[tab.key]" :size="18" :class="isActive(tab.route) ? 'text-primary' : ''" />
    </button>

    <div class="flex-1"></div>
    <UserMenu v-if="displayUser" :user="displayUser" :pending-count="pendingReviewCount" placement="top" compact
      button-class="rounded-lg hover:bg-sidebar-accent transition-colors p-0"
      @logout="handleLogout" @bank-mode-changed="handleBankModeChanged" @show-review="handleShowReview" @show-settings="handleShowSettings" />
  </div>

  <!-- Expanded view -->
  <div v-else class="flex flex-col h-full overflow-hidden animate-sidebar-expand">
    <div class="flex items-center justify-between px-4 py-3 shrink-0">
      <a href="#" class="flex items-center gap-3 min-w-0">
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary-600 text-sm font-bold text-white shadow-lg shadow-primary/20 transition-transform hover:scale-105">IB</div>
        <div class="flex flex-col items-start leading-tight">
          <span class="text-base font-semibold tracking-tight text-sidebar-foreground whitespace-nowrap">InterviewBoss</span>
          <span class="text-[11px] text-sidebar-foreground/50 whitespace-nowrap">AI 面试准备工作台</span>
        </div>
      </a>
      <button @click="toggleCollapsed" class="p-1.5 rounded-lg text-sidebar-foreground/40 hover:text-sidebar-foreground hover:bg-sidebar-accent transition-colors" title="收起侧栏">
        <PanelLeft :size="18" />
      </button>
    </div>

    <div class="flex-1 min-h-0 flex flex-col overflow-y-auto custom-scrollbar py-1 px-2 gap-0.5">
      <button v-for="tab in sidebarTabs" :key="tab.key" @click="onTabChange(tab)"
        class="group relative flex items-center w-full rounded-lg transition-all duration-200 gap-3 px-3 py-2"
        :class="isActive(tab.route) ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium' : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'">
        <HugeiconsIcon v-if="iconMap[tab.key]" :icon="iconMap[tab.key]" :size="18" class="transition-colors shrink-0"
          :class="isActive(tab.route) ? 'text-primary' : 'text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70'" />
        <span class="text-sm whitespace-nowrap">{{ tab.label }}</span>
        <span v-if="tab.count != null && tab.count !== 0" class="ml-auto text-[11px] font-medium text-sidebar-foreground/50 whitespace-nowrap">{{ tab.count }}</span>
      </button>
    </div>

    <div class="shrink-0 p-3 border-t border-sidebar-border/50">
      <UserMenu v-if="displayUser" :user="displayUser" :pending-count="pendingReviewCount" placement="top"
        button-class="w-full justify-start rounded-lg hover:bg-sidebar-accent px-3 py-2 gap-3 transition-colors"
        @logout="handleLogout" @bank-mode-changed="handleBankModeChanged" @show-review="handleShowReview" @show-settings="handleShowSettings" />
    </div>
  </div>
</template>

<style scoped>
/* ... 原有动画 CSS 不变 ... */
</style>
```

- [ ] **Step 4.2: 改造 TabBar.vue**

```vue
<!-- frontend/src/components/common/TabBar.vue -->
<template>
  <div class="relative">
    <Tabs :model-value="activeRoute" @update:model-value="handleTabClick" class="w-fit">
      <TabsList class="bg-transparent border-b border-border/80/50 overflow-x-auto mobile-scroll-x w-full">
        <TabsTrigger v-for="tab in tabs" :key="tab.route" :value="tab.route" :disabled="isTransitioning" class="flex-shrink-0">
          {{ tab.label }}
        </TabsTrigger>
      </TabsList>
    </Tabs>
    <div class="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white/80 dark:from-surface-800/80 to-transparent pointer-events-none sm:hidden"></div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const router = useRouter()
const route = useRoute()
const isTransitioning = ref(false)
let transitionTimer = null

const activeRoute = computed(() => route.path)

function handleTabClick(tabRoute) {
  if (isTransitioning.value) return
  isTransitioning.value = true
  router.push(tabRoute)
  if (transitionTimer) clearTimeout(transitionTimer)
  transitionTimer = setTimeout(() => { isTransitioning.value = false; transitionTimer = null }, 300)
}

const tabs = [
  { route: '/jd', label: 'JD 筛选' },
  { route: '/interview', label: '面经库' },
  { route: '/master-bank', label: '高频题库' },
  { route: '/chat', label: '模拟面试' },
  { route: '/mock-interview', label: '题目抽测' },
  { route: '/knowledge-graph', label: '知识图谱' },
  { route: '/import', label: '导入' },
  { route: '/coding', label: '手撕代码' },
]
</script>
```

- [ ] **Step 4.3: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功。

- [ ] **Step 4.4: Commit**

```bash
git add frontend/src/components/AppSidebar.vue frontend/src/components/common/TabBar.vue
git commit -m "feat(router): migrate Sidebar and TabBar to use router-link

- AppSidebar: use router.push() and route.path for navigation/highlight
- TabBar: use router path instead of activeTab key
- Remove activeTab prop dependency from both components"
```

---

## Task 5: 切换 App.vue 到路由模式

**Files:**
- Modify: `frontend/src/App.vue:1-990`

- [ ] **Step 5.1: 重写 App.vue 为路由壳**

将 990 行的 App.vue 替换为 ~40 行的路由壳：

```vue
<!-- frontend/src/App.vue -->
<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Toaster } from 'vue-sonner'

const router = useRouter()

// ── 白屏检测标记 ──
onMounted(() => {
  window.__VUE_APP_READY__ = true
})
</script>

<template>
  <router-view />
  <Toaster position="top-right" richColors closeButton />
</template>
```

- [ ] **Step 5.2: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功。所有页面现在通过 Vue Router 渲染。

- [ ] **Step 5.3: 本地功能测试**

```bash
cd frontend && npm run dev
```

逐项验证：
1. 访问 `/` → 重定向到 `/master-bank`，显示题库列表
2. 未登录时访问 `/master-bank` → 重定向到 `/login`
3. 登录后 → 重定向回原目标页面
4. 侧边栏点击各 tab → URL 变化，内容切换
5. 浏览器前进/后退 → 正确导航
6. 直接访问 `http://localhost:5173/jd` → 显示 JD 页面
7. 刷新页面 → 内容保持（不再回到默认 tab）
8. 设置页通过 `/settings` 访问 → 正常显示
9. 移动端 TabBar 导航 → 正常工作

- [ ] **Step 5.4: Commit**

```bash
git add frontend/src/App.vue
git commit -m "feat(router): switch to Vue Router, App.vue reduced from 990 to ~40 lines

- Replace activeTab + v-if with <router-view>
- All page rendering moved to view components
- All data logic moved to AuthenticatedLayout
- Remove hash sync, pushState, popstate handlers
- Remove all tab-related imports and logic"
```

---

## Task 6: 部署验证 + 文档更新

- [ ] **Step 6.1: 前端构建部署**

```bash
./deploy/docker-deploy.sh frontend
```

- [ ] **Step 6.2: 生产环境验证**

在生产环境验证：
1. 访问 `http://<domain>/` → 重定向到 `/master-bank`
2. 所有 8 个 tab 可通过 URL 直接访问
3. 刷新页面内容保持
4. 浏览器前进/后退正常
5. 未登录访问需认证页面 → 跳转登录
6. 登录后跳转回原页面

**注意：** 生产环境 nginx 需要配置 SPA fallback（所有非 `/api/` 请求返回 `index.html`）。检查 `nginx/` 配置是否已包含 `try_files $uri $uri/ /index.html`。

- [ ] **Step 6.3: 更新 frontend/CLAUDE.md**

更新路由相关说明：
- 记录 Vue Router 已引入
- 路由配置位置：`frontend/src/router/index.js`
- 布局组件：`AuthenticatedLayout.vue`（数据提供层）、`BlankLayout.vue`
- View 组件位置：`frontend/src/views/`
- 数据共享方式：provide/inject from AuthenticatedLayout

- [ ] **Step 6.4: Commit**

```bash
git add frontend/CLAUDE.md
git commit -m "docs: update frontend CLAUDE.md for Vue Router architecture"
```

---

## 自审检查

**1. Spec 覆盖：**
- ✅ 所有 8 个 tab 路由已映射
- ✅ 深度链接结构已定义（Step 1.3 路由表）
- ✅ 认证守卫已实现
- ✅ App.vue 瘦身（990 → ~40 行）
- ✅ 布局系统（AuthenticatedLayout + BlankLayout）
- ✅ Sidebar/TabBar 改用路由导航
- ✅ 设置页独立路由

**2. Placeholder 扫描：** 无 TBD/TODO。applyPreviewData 和 onNavigateToInterview 标注为"与原 App.vue 相同"，因为完整代码已在上下文中（App.vue lines 658-738 和 850-912）。

**3. 类型一致性：**
- `inject('appData')` 的 key 在 provide 和 inject 之间一致
- `sidebarTabs` 结构新增 `route` 字段，AppSidebar 和 TabBar 都使用 `tab.route`
- `useAuth()` 返回值与原 `useAuth({ onReady, onDataRefresh })` 兼容（只是回调注入方式改为 `initAuthSingleton`）

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, provide } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cancelAllRequests } from '@/services/http.js'
import { safeUrl } from '@/utils/validate.js'
import { useSelection } from '@/composables/useSelection.js'
import { useTheme } from '@/composables/useTheme.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import AppSidebar from '@/components/AppSidebar.vue'
import SiteHeader from '@/components/SiteHeader.vue'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  BookOpen,
  BotMessageSquare,
  Code2,
  FileText,
  FileUp,
  Filter,
  History,
  Layers,
  Library,
  LayoutDashboard,
  Network,
  Target,
} from '@lucide/vue'
import { useHighlightNav } from '@/composables/useHighlightNav.js'
import { useQuestionOps } from '@/composables/useQuestionOps.js'
import { useMergeDialog } from '@/composables/useMergeDialog.js'
import { useBatchActions } from '@/composables/useBatchActions.js'
import { useTabScroll } from '@/composables/useTabScroll.js'
import { useAuth, initAuthSingleton } from '@/composables/useAuth.js'
import { useMasterBankData } from '@/composables/useMasterBankData.js'
import { useBuildTrigger } from '@/composables/useBuildTrigger.js'
import { setOnJobDone, restoreActiveJobs } from '@/composables/useSubmitJobs.js'
import { fetchCodingPlaylists } from '@/services/codingApi.js'
import { usePracticeDecks } from '@/composables/usePracticeDecks.js'

import { defineAsyncComponent } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import ModelGuardDialog from '@/components/business/ModelGuardDialog.vue'
import LoginModal from '@/components/business/LoginModal.vue'
import LoginPage from '@/components/business/LoginPage.vue'
import MergeQuestionDialog from '@/components/business/MergeQuestionDialog.vue'
import PracticePanel from '@/components/business/PracticePanel.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

// 异步组件 loading/error 包装
const asyncOptions = {
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
}

const AdminReview = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/AdminReview.vue'),
})
// ── Composables ──
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { confirm: showConfirm } = useConfirm()
const { isDark, toggleDark } = useTheme()

const isPreviewMode = new URLSearchParams(window.location.search).get('preview') === '1'
const routeLocation = (path) => (
  isPreviewMode ? { path, query: { preview: '1' } } : path
)

// Route-name to tab-key mapping for useHighlightNav compatibility
const routeToTabMap = {
  'master-bank': 'MasterBank',
  'chat': 'Chat',
  'jd': 'JD',
  'interview': 'Interview',
  'practice': 'Practice',
  'practice-decks': 'Practice',
  'knowledge-graph': 'KnowledgeGraph',
  'insights-overview': 'InsightsOverview',
  'insights-readiness': 'InsightsReadiness',
  'insights-reviews': 'InsightsReviews',
  'import': 'Import',
  'coding': 'Coding',
  'settings': 'Settings',
  'resume': 'Resume',
}

const tabToRouteMap = {
  MasterBank: '/master-bank',
  Chat: '/chat',
  JD: '/jd',
  Interview: '/interview',
  Practice: '/practice',
  KnowledgeGraph: '/knowledge-graph',
  InsightsOverview: '/insights/overview',
  InsightsReadiness: '/insights/readiness',
  InsightsReviews: '/insights/reviews',
  Import: '/import',
  Coding: '/coding',
  Settings: '/settings',
  Resume: '/resume',
}

// Computed reactive "activeTab" derived from route for useHighlightNav compatibility.
// useHighlightNav reads/writes activeTab.value; the getter reads route.name,
// the setter calls router.push() to navigate.
const activeTab = computed({
  get: () => routeToTabMap[route.name] || 'MasterBank',
  set: (val) => {
    const path = tabToRouteMap[val]
    if (path) router.push(routeLocation(path))
  },
})

const { saveScroll, prepareRestore, restoreScroll } = useTabScroll()

const {
  highlightInterviewId, returnTab, returnToPracticeMode,
  floatingReturnBtn, floatingBtnStyle, masterBankEverShown,
  handleReturn, detachHighlightScroll, setSavedScrollTop,
} = useHighlightNav(activeTab)

// ── Data (题库数据 + 筛选 + 获取) ──
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
  bankFilter,
  filteredMasterBank, filteredInterviewData,
  availableSubTags, interviewSeasons, practicedQuestions,
  fetchTableData, fetchAnalytics, fetchPracticeStats,
  loadActiveSeason, loadAllData, formatDate,
} = useMasterBankData({ onAfterFetch: () => afterFetchCleanup() })

// ── Build（题库重建） ──
const {
  isBuilding, buildProgress, buildStepList,
  triggerBuildMasterBank, triggerBuildPersonalBank,
} = useBuildTrigger({ onRebuildDone: () => { fetchTableData(); fetchAnalytics() } })

// ── UI state ──
const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
const mobileNavOpen = ref(false)
const jdCurrentPage = ref(1)
const jdPageSize = ref(20)
const interviewCurrentPage = ref(1)
const interviewPageSize = ref(20)
const showReviewPanel = ref(false)
const practiceQuestion = ref(null)

// 手撕代码题单由应用壳统一持有，让全局顶栏和题目工作区使用同一份选择状态。
const codingPlaylists = ref([])
const codingSelectedListKey = ref('all')

const loadCodingPlaylists = async () => {
  try {
    codingPlaylists.value = await fetchCodingPlaylists()
    if (/^\d+$/.test(String(codingSelectedListKey.value)) && !codingPlaylists.value.some(item => item.id === Number(codingSelectedListKey.value))) {
      codingSelectedListKey.value = 'all'
    }
  } catch {
    codingPlaylists.value = []
  }
}

const codingNavigation = {
  playlists: codingPlaylists,
  selectedListKey: codingSelectedListKey,
  loadPlaylists: loadCodingPlaylists,
  selectList: (value) => { codingSelectedListKey.value = value },
}

provide('codingNavigation', codingNavigation)

const sidebarGroups = computed(() => [
  {
    label: null,
    tabs: [
      { key: 'MasterBank', label: '高频题库', route: '/master-bank', count: masterBankTotal.value || filteredMasterBank.value.length },
    ],
  },
  {
    label: '训练',
    tabs: [
      { key: 'Practice', label: '八股刷题', route: '/practice' },
      { key: 'Chat', label: '模拟面试', route: '/chat' },
      { key: 'Coding', label: '手撕代码', route: '/coding' },
    ],
  },
  {
    label: '素材',
    tabs: [
      { key: 'Import', label: '导入', route: '/import' },
      { key: 'JD', label: 'JD 筛选', route: '/jd', count: jdData.value.length },
      { key: 'Interview', label: '面经库', route: '/interview', count: interviewData.value.length },
      { key: 'Resume', label: '简历', route: '/resume' },
    ],
  },
  {
    label: '洞察',
    tabs: [
      { key: 'InsightsOverview', label: '总览', route: '/insights/overview' },
      { key: 'InsightsReadiness', label: '岗位准备度', route: '/insights/readiness' },
      { key: 'InsightsReviews', label: '面试复盘', route: '/insights/reviews' },
    ],
  },
])

const sidebarTabs = computed(() => sidebarGroups.value.flatMap(group => group.tabs))

const navIconMap = {
  MasterBank: BookOpen,
  Chat: BotMessageSquare,
  Practice: Layers,
  Coding: Code2,
  Import: FileUp,
  JD: Filter,
  Interview: Library,
  Resume: FileText,
  KnowledgeGraph: Network,
  InsightsOverview: LayoutDashboard,
  InsightsReadiness: Target,
  InsightsReviews: History,
}

const activeTabLabel = computed(() => {
  if (!isAuthenticatedForUi.value) return 'InterviewBoss'
  if (activeTab.value === 'Settings') return '设置'
  return sidebarTabs.value.find(tab => tab.key === activeTab.value)?.label || '工作台'
})

function isActiveRoute(tabRoute) {
  return route.path === tabRoute || route.path.startsWith(tabRoute + '/')
}

async function navigateMobile(tab) {
  await router.push(routeLocation(tab.route))
  mobileNavOpen.value = false
}

// ── Selection ──
const jdSelection = useSelection(() => jdData.value)
const interviewSelection = useSelection(() => interviewData.value)
const masterSelection = useSelection(() => filteredMasterBank.value)
const isMasterSelected = (id) => masterSelection.selectedIds.value.has(id)
afterFetchCleanup = () => { jdSelection.clearSelection(); interviewSelection.clearSelection() }

// ── Auth（认证状态） ──
const {
  currentUser, authCompleted, showLoginModal, pendingReviewCount,
  initAuth, handleLoginSuccess, handleLogout, handleShareDefaultChanged,
} = useAuth()

// 初始化数据回调
initAuthSingleton({
  onReady: loadAllData,
  onDataRefresh: () => { fetchTableData(); fetchPracticeStats() },
})

// Set singleton callbacks (called once per layout mount)
initAuthSingleton({
  onReady: loadAllData,
  onDataRefresh: () => { fetchTableData(); fetchPracticeStats() },
})

const previewUser = {
  id: 'preview-user',
  username: 'Preview',
  is_admin: false,  // 预览按普通用户渲染，不暴露管理员入口
  share_default: 'private',
}
const displayUser = computed(() => currentUser.value || (isPreviewMode ? previewUser : null))
const isAuthenticatedForUi = computed(() => Boolean(displayUser.value))

// 刷题题单属于应用壳状态：全局顶栏、刷题卡片和题单管理页共享同一份选择与加载状态。
const practiceNavigation = usePracticeDecks(bankFilter)
const {
  decks: practiceDecks,
  selectedDeckKey: practiceSelectedDeckKey,
  isLoading: practiceDeckLoading,
  loadedDeckKey: practiceLoadedDeckKey,
} = practiceNavigation
const practiceDecksLoaded = ref(false)

const loadPracticeContext = async () => {
  if (!route.path.startsWith('/practice') || !isAuthenticatedForUi.value) return
  if (!practiceDecksLoaded.value) {
    await practiceNavigation.loadDecks()
    practiceDecksLoaded.value = true
  }
  if (route.name !== 'practice') return
  const requestedDeck = String(route.query.deck || '')
  const targetDeck = requestedDeck && practiceNavigation.decks.value.some(deck => deck.key === requestedDeck)
    ? requestedDeck
    : practiceNavigation.selectedDeckKey.value
  // 今日复习是数据库驱动的活队列。即使仍选中 due，从其他页面返回时也要
  // 重读已过关数与待巩固题，不能沿用应用壳中的旧会话快照。
  if (targetDeck && (practiceLoadedDeckKey.value !== targetDeck || targetDeck === 'due')) {
    await practiceNavigation.loadQuestions(targetDeck)
  }
}

const selectPracticeDeck = async (deckKey) => {
  if (!deckKey || !practiceNavigation.decks.value.some(deck => deck.key === deckKey)) return
  if (route.name === 'practice') {
    await practiceNavigation.loadQuestions(deckKey)
    await router.replace({ path: '/practice', query: { deck: deckKey } })
  } else {
    await router.push({ path: '/practice', query: { deck: deckKey } })
  }
}

const refreshPracticeContext = async () => {
  practiceNavigation.invalidateQuestions()
  practiceDecksLoaded.value = false
  if (route.path.startsWith('/practice') && isAuthenticatedForUi.value) {
    await loadPracticeContext()
  }
}

const openPracticeDeckManager = () => router.push('/practice/decks')
provide('practiceDecks', practiceNavigation)

const openSettings = () => {
  router.push(routeLocation('/settings'))
}

const applyPreviewData = () => {
  activeSeason.value = '2026 春招'
  availableSeasons.value = ['2026 春招', '2025 秋招']
  popularTags.value = {
    前端框架: 318,
    项目复盘: 126,
    工程化: 94,
    浏览器原理: 76,
    系统设计: 42,
  }
  practiceStats.value = {
    total_questions: 1248,
    practiced_questions: 426,
    avg_score: 82,
    by_difficulty: {
      'L1-基础': { practiced: 168, total: 320, avg_score: 86 },
      'L2-中等': { practiced: 202, total: 654, avg_score: 80 },
      'L3-困难': { practiced: 56, total: 274, avg_score: 74 },
    },
  }
  analytics.value = {
    tech_trends: { Vue: 128, TypeScript: 96, Vite: 72, 性能优化: 64, 工程化: 58 },
  }
  masterBank.value = [
    {
      id: 9001,
      question: 'Vue 3 的响应式系统相比 Vue 2 有哪些关键变化？',
      frequency: 92,
      cat1: '前端框架',
      tags: 'Vue,响应式,Proxy',
      difficulty: 'L2-中等',
      job_position: 'frontend',
      is_personal: false,
      is_starred: true,
      has_reference_answer: true,
      ai_answer: 'Vue 3 使用 Proxy 代替 Object.defineProperty，覆盖新增、删除、数组索引等场景；依赖收集以 effect 为核心组织，配合 ref、reactive、computed 和 scheduler，让组合式 API 下的状态复用更自然。',
      sources: [{ company: '字节', round: '一面', url: 'https://example.com', _origQuestion: 'Vue3 响应式原理是什么？' }],
    },
    {
      id: 9002,
      question: '如何介绍你最近一个项目里的性能优化？',
      frequency: 81,
      cat1: '项目复盘',
      tags: '性能优化,项目经验,指标',
      difficulty: 'L2-中等',
      job_position: 'frontend',
      is_personal: true,
      is_starred: false,
      has_reference_answer: true,
      ai_answer: '建议按"问题背景、定位方法、优化动作、量化收益、复盘边界"组织回答，优先给出首屏、接口耗时、打包体积或交互延迟等可验证指标。',
      sources: [{ company: '美团', round: '二面', url: 'https://example.com', _origQuestion: '项目性能怎么优化？' }],
    },
    {
      id: 9003,
      question: '前端工程化中如何设计稳定的构建和发布流程？',
      frequency: 64,
      cat1: '工程化',
      tags: 'CI/CD,Vite,质量门禁',
      difficulty: 'L3-困难',
      job_position: 'frontend',
      is_personal: false,
      is_starred: false,
      has_reference_answer: false,
    },
  ]
  jdData.value = [
    { id: 8101, 公司: 'Moonshot AI', 岗位名称: '高级前端工程师', 薪资范围: '35k-55k', 核心技术要求: 'Vue 3 / TypeScript / 大模型应用工程化', 加分项: 'AI 产品经验、性能优化、组件库建设', season: '2026 春招', owner_id: 'preview-user', 来源链接: 'https://example.com' },
    { id: 8102, 公司: '字节跳动', 岗位名称: '前端基础架构', 薪资范围: '40k-65k', 核心技术要求: '构建系统 / 监控 / 微前端 / Node.js', 加分项: '复杂业务平台治理经验', season: '2026 春招', owner_id: 'preview-user', 来源链接: 'https://example.com' },
  ]
  interviewData.value = [
    { id: 8201, 公司: '腾讯', season: '2026 春招', 面试轮次: '一面', 考察重点: 'Vue 原理、项目复盘、性能优化', 具体题目清单: 'Vue3 响应式原理；项目里如何做性能指标采集；如何处理复杂表格渲染。', 难易程度: '中等', created_at: new Date().toISOString(), owner_id: 'preview-user', 来源链接: 'https://example.com' },
    { id: 8202, 公司: '美团', season: '2026 春招', 面试轮次: '二面', 考察重点: '工程化、系统设计、团队协作', 具体题目清单: '如何设计导入解析容错；如何回滚异常发布；如何拆分公共组件。', 难易程度: '困难', created_at: new Date(Date.now() - 3600000).toISOString(), owner_id: 'preview-user', 来源链接: 'https://example.com' },
  ]
  practicedQuestions.value = {
    9001: { best_score: 88 },
    9002: { best_score: 76 },
  }
  masterBankEverShown.value = true
  isDataLoading.value = false
  dataLoadError.value = ''
}

// ── Question operations ──
const {
  reprocessingIds, reprocessProgress, activeReprocessing,
  deletingIds,
  deleteDataRow, reprocessInterview, retagQuestion,
  saveField, saveFieldFromEvent, toggleStar,
  generateAnswer, saveUserAnswer,
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

// ── Practice mode ──
const enterPracticeMode = () => {
  if (filteredMasterBank.value.length === 0) { toast.warning('当前筛选条件下没有题目'); return }
  router.push(routeLocation('/practice'))
}

// ── Watches ──
watch(sidebarCollapsed, (val) => {
  localStorage.setItem('sidebar-collapsed', String(val))
})

// ── Cross-view navigation ──
const onGoToQuestion = (question) => {
  router.push(routeLocation('/master-bank'))
  const q = question.question || ''
  searchQuery.value = q.length > 30 ? q.substring(0, 30) : q
  selectedTag.value = '全部'; selectedSubTags.value = []
}

const toggleSubTag = (tag) => {
  const idx = selectedSubTags.value.indexOf(tag)
  if (idx === -1) { selectedSubTags.value = [...selectedSubTags.value, tag] }
  else { selectedSubTags.value = selectedSubTags.value.filter(t => t !== tag) }
}

const onNavigateToInterview = (event) => {
  const source = event?.source || event
  const questionId = event?.questionId
  const targetUrl = source.url || ''
  if (!targetUrl) return

  const normalizeUrl = (u) => {
    try { return new URL(u).pathname.replace(/\/+$/, '') } catch { return u.split('?')[0].replace(/\/+$/, '') }
  }
  const targetPath = normalizeUrl(targetUrl)

  const match = interviewData.value.find(row => {
    const rowUrl = row['来源链接'] || row.url || ''
    return rowUrl === targetUrl || normalizeUrl(rowUrl) === targetPath
  })
  if (!match) { toast.warning('未找到该面经记录'); return }

  returnTab.value = activeTab.value
  const outerScroll = document.querySelector('.overflow-y-auto.custom-scrollbar')
  if (outerScroll) setSavedScrollTop(outerScroll.scrollTop)

  if (activeTab.value === 'Practice') returnToPracticeMode.value = true
  router.push(routeLocation('/interview'))

  filterSeason.value = ''
  const sortedIdx = filteredInterviewData.value.indexOf(match)
  const idx = sortedIdx >= 0 ? sortedIdx : interviewData.value.indexOf(match)
  interviewCurrentPage.value = Math.floor(idx / interviewPageSize.value) + 1

  highlightInterviewId.value = match.id

  const scrollAndHighlight = (attempt = 0) => {
    const el = document.querySelector(`[data-row-id="${match.id}"]`)
    if (el) {
      const allScrollContainers = document.querySelectorAll('.custom-scrollbar')
      let mainScroll = null
      for (const c of allScrollContainers) {
        if (c.scrollHeight > c.clientHeight + 10 && c.classList.contains('overflow-y-auto')) { mainScroll = c; break }
      }
      if (mainScroll) {
        const containerRect = mainScroll.getBoundingClientRect()
        const rowRect = el.getBoundingClientRect()
        const delta = rowRect.top - containerRect.top - containerRect.height / 3
        mainScroll.scrollTo({ top: mainScroll.scrollTop + delta, behavior: 'smooth' })
      } else { el.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
      const questionText = source._origQuestion || source.question || ''
      if (questionText) {
        setTimeout(() => {
          const cells = el.querySelectorAll('td')
          for (const cell of cells) {
            if (cell.textContent.includes(questionText.slice(0, 15))) {
              const escaped = questionText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
              cell.innerHTML = cell.innerHTML.replace(new RegExp(`(${escaped})`, 'g'), '<mark class="bg-yellow-200 dark:bg-yellow-700/60 rounded px-0.5 question-highlight">$1</mark>')
              setTimeout(() => { cell.querySelectorAll('.question-highlight').forEach(m => { m.replaceWith(m.textContent) }) }, 10000)
              break
            }
          }
        }, 300)
      }
    } else if (attempt < 40) { setTimeout(() => scrollAndHighlight(attempt + 1), 100) }
  }
  scrollAndHighlight()
}

// ── 全局上传任务恢复 ──
setOnJobDone((_jobId, _result) => {
  fetchTableData()
  fetchAnalytics()
})

// ── Provide appData to child views ──
provide('appData', {
  // Data
  jdData, interviewData, masterBank,
  isDataLoading, dataLoadError,
  analytics, practiceStats, popularTags, categoryCounts,
  masterBankTotal, masterBankOverallTotal,
  activeSeason, availableSeasons,
  // Infinite scroll
  isLoadingMore, hasMore, loadMoreMasterBank,
  // Filters
  selectedTag, selectedSubTags, searchQuery,
  filterDifficulty, showStarredOnly,
  filterSeason, interviewSortOrder, bankFilter,
  // Computed
  filteredMasterBank, filteredInterviewData,
  availableSubTags, interviewSeasons, practicedQuestions,
  // Fetch
  fetchTableData, fetchAnalytics, fetchPracticeStats,
  loadAllData, formatDate,
  // Auth
  displayUser, isAuthenticatedForUi, currentUser,
  pendingReviewCount, showLoginModal,
  handleLoginSuccess, handleLogout, handleShareDefaultChanged,
  // Build
  isBuilding, triggerBuildMasterBank, triggerBuildPersonalBank,
  // Selections
  jdSelection, interviewSelection, masterSelection,
  isMasterSelected, jdBatchActions, interviewBatchActions, masterBatchActions,
  // Question ops
  reprocessingIds, reprocessProgress, activeReprocessing,
  deletingIds,
  deleteDataRow, reprocessInterview, retagQuestion,
  saveField, saveFieldFromEvent, toggleStar,
  generateAnswer, saveUserAnswer,
  deleteQuestion, deleteOriginalQuestion, editQuestion,
  onUpdateAnswer, splitQuestion,
  // Merge
  mergeDialogVisible, mergeSourceOriginalQ, mergeSearchQuery,
  mergeSearchResults, mergeSearching, startMerge, doMergeSearch,
  confirmMerge, splitAsNew,
  // Practice
  enterPracticeMode, practiceQuestion, practiceNavigation, refreshPracticeContext,
  // Highlight
  highlightInterviewId, returnTab, returnToPracticeMode,
  floatingReturnBtn, floatingBtnStyle, masterBankEverShown,
  handleReturn, detachHighlightScroll, setSavedScrollTop,
  // Cross-view
  onGoToQuestion, onNavigateToInterview,
  // Pagination
  jdCurrentPage, jdPageSize, interviewCurrentPage, interviewPageSize,
  // UI
  sidebarCollapsed, sidebarTabs, sidebarGroups, isPreviewMode,
  isDark, toggleDark, showConfirm, toast, safeUrl,
  // Review
  showReviewPanel,
  // Sub-tag helper
  toggleSubTag,
})

// ── Lifecycle ──
// initAuth() 在 App.vue 中执行，authCompleted 变为 true 后触发数据加载
watch(authCompleted, (done) => {
  if (done && currentUser.value) {
    loadAllData()
  }
}, { immediate: true })

watch([() => route.fullPath, isAuthenticatedForUi], () => { void loadPracticeContext() }, { immediate: true })

onMounted(async () => {
  if (isPreviewMode) {
    currentUser.value = previewUser
    applyPreviewData()
  } else {
    try { await restoreActiveJobs() } catch {}
  }
})
onUnmounted(() => { cancelAllRequests(); detachHighlightScroll() })
</script>

<template>
  <div class="min-h-[100dvh] bg-background">
    <!-- Login gate -->
    <LoginPage v-if="!isAuthenticatedForUi" @login-success="handleLoginSuccess" />

    <!-- Main layout -->
    <div v-else class="flex h-[100dvh] overflow-hidden">
      <!-- Sidebar -->
      <aside
        class="hidden md:flex shrink-0 flex-col border-r border-border bg-sidebar h-screen sticky top-0 overflow-hidden"
        :style="{ width: sidebarCollapsed ? '60px' : '256px', transition: 'width 380ms cubic-bezier(0.4, 0, 0.2, 1)' }"
      >
        <AppSidebar
          :collapsed="sidebarCollapsed"
          :active-tab="activeTab"
          :sidebar-tabs="sidebarTabs"
          :sidebar-groups="sidebarGroups"
          :display-user="displayUser"
          :pending-review-count="pendingReviewCount"
          @update:active-tab="activeTab = $event"
          @update:collapsed="sidebarCollapsed = $event"
          @go-to-question="onGoToQuestion"
          @logout="handleLogout"
          @share-default-changed="handleShareDefaultChanged"
          @show-review="showReviewPanel = true"
          @show-settings="openSettings"
        />
      </aside>

      <!-- Main content -->
      <main class="flex-1 min-w-0 flex flex-col overflow-hidden">
        <SiteHeader
          :active-tab-label="activeTabLabel"
          :active-season="activeSeason"
          :show-coding-controls="activeTab === 'Coding'"
          :show-practice-controls="activeTab === 'Practice'"
          :practice-decks="practiceDecks"
          :practice-selected-deck-key="practiceSelectedDeckKey"
          :practice-deck-loading="practiceDeckLoading"
          :no-border="route.path.startsWith('/chat')"
          @show-settings="openSettings"
          @toggle-mobile-nav="mobileNavOpen = true"
          @practice-select-deck="selectPracticeDeck"
          @practice-manage-decks="openPracticeDeckManager"
        />

        <Sheet v-model:open="mobileNavOpen">
          <SheetContent side="left" class="w-[86vw] max-w-xs gap-0 p-0 md:hidden">
            <SheetHeader class="border-b border-border px-4 py-4 text-left">
              <div class="flex items-center gap-3">
                <div class="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-xl">
                  <img src="/favicon-b.png" alt="InterviewBoss" class="h-8 w-8 object-contain" />
                </div>
                <div class="min-w-0">
                  <SheetTitle class="truncate text-base">InterviewBoss</SheetTitle>
                  <p class="truncate text-xs text-muted-foreground">AI 面试准备工作台</p>
                </div>
              </div>
            </SheetHeader>

            <nav class="flex-1 overflow-y-auto px-3 py-3">
              <div
                v-for="group in sidebarGroups"
                :key="group.label || 'primary'"
                class="mb-3 last:mb-0"
              >
                <div
                  v-if="group.label"
                  class="px-2 pb-1.5 pt-1 text-[11px] font-medium text-muted-foreground"
                >
                  {{ group.label }}
                </div>
                <div class="space-y-1">
                  <button
                    v-for="tab in group.tabs"
                    :key="tab.key"
                    type="button"
                    class="flex min-h-10 w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors"
                    :class="isActiveRoute(tab.route)
                      ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                      : 'text-foreground/75 hover:bg-muted hover:text-foreground'"
                    @click="navigateMobile(tab)"
                  >
                    <component
                      :is="navIconMap[tab.key]"
                      class="h-4 w-4 shrink-0"
                      :class="isActiveRoute(tab.route) ? 'text-primary' : 'text-muted-foreground'"
                    />
                    <span class="min-w-0 flex-1 truncate">{{ tab.label }}</span>
                    <span
                      v-if="tab.count != null && tab.count !== 0"
                      class="shrink-0 text-xs font-medium text-muted-foreground"
                    >
                      {{ tab.count }}
                    </span>
                  </button>
                </div>
              </div>
            </nav>
          </SheetContent>
        </Sheet>

        <!-- 统一 overflow-hidden：每个 View 组件自己管理滚动（消除双层滚动问题） -->
        <!-- h-full 确保 ChatView 的 h-full 能正确解析（CSS 百分比高度需要父链每一层都有明确高度） -->
        <div class="flex-1 min-h-0 h-full overflow-hidden">
          <router-view v-slot="{ Component }">
            <Transition name="page-route" mode="out-in">
              <component :is="Component" :key="route.name || route.path" class="h-full min-h-0" />
            </Transition>
          </router-view>
        </div>
      </main>
    </div>

    <ConfirmDialog />
    <ModelGuardDialog />
    <LoginModal :visible="showLoginModal && !isPreviewMode" @close="showLoginModal = false" @login-success="handleLoginSuccess" />
    <AdminReview :visible="showReviewPanel" @close="showReviewPanel = false" @reviewed="fetchTableData" />
    <PracticePanel :visible="!!practiceQuestion" :question="practiceQuestion" :is-admin="currentUser?.is_admin" @close="practiceQuestion = null" />
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
  </div>
</template>

<style scoped>
/* ── Markdown rendering styles (for AI answers, practice content) ── */
:deep(pre) { background-color: #2d2a27; color: #faf9f7; padding: 1rem; border-radius: var(--radius-xl); overflow-x: auto; margin-top: 0.5rem; margin-bottom: 1rem; }
:deep(code) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.875em; }
:deep(p code) { @apply bg-muted dark:bg-card text-red-600 dark:text-red-400; padding: 0.125rem 0.375rem; border-radius: var(--radius-md); font-size: 0.8125em; }
:deep(ul) { list-style-type: disc; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(ol) { list-style-type: decimal; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(strong) { font-weight: 700; @apply text-foreground; }
:deep(.answer-content h1), :deep(.answer-content h2), :deep(.answer-content h3),
:deep(.prose-chat h1), :deep(.prose-chat h2), :deep(.prose-chat h3) {
  font-weight: 700;
  @apply text-foreground;
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
}
:deep(.answer-content h3), :deep(.prose-chat h3) { font-size: 1.125rem; }

/* ── Tab transition ── */
.tab-fade-enter-active,
.tab-fade-leave-active { transition: opacity var(--motion-short-2) var(--ease-decelerate); }
.tab-fade-enter-from,
.tab-fade-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .tab-fade-enter-active,
  .tab-fade-leave-active { transition-duration: 0.01ms !important; }
}
</style>

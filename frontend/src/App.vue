<template>
  <div class="min-h-screen bg-slate-50">
    <!-- Top bar -->
    <nav class="sticky top-0 z-50 bg-white border-b border-gray-200 shadow-sm">
      <div class="max-w-[98%] mx-auto px-5 lg:px-8 h-14 flex items-center justify-between">
        <h1 class="text-lg lg:text-xl font-bold text-gray-900">面试题库管理系统</h1>
        <div class="flex items-center gap-3">
          <span v-if="activeSeason" class="text-xs bg-indigo-100 text-indigo-700 px-2.5 py-1 rounded-full font-medium">
            {{ activeSeason }}
          </span>
          <UserMenu
            v-if="currentUser"
            :user="currentUser"
            :pending-count="pendingReviewCount"
            @logout="handleLogout"
            @bank-mode-changed="handleBankModeChanged"
            @show-review="showReviewPanel = true"
          />
          <button
            v-else
            @click="showLoginModal = true"
            class="text-sm bg-blue-600 hover:bg-blue-700 text-white px-4 py-1.5 rounded-lg transition font-medium"
          >登录</button>
          <button
            @click="showSettings = true"
            class="p-2 rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-100 transition"
            title="系统配置"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
          </button>
        </div>
      </div>
    </nav>

    <!-- Settings modal -->
    <SettingsPanel
      :visible="showSettings"
      :active-season="activeSeason"
      @close="showSettings = false"
      @update:active-season="activeSeason = $event"
    />

    <!-- Login gate: block content until authenticated -->
    <div v-if="!currentUser" class="flex flex-col items-center justify-center min-h-[60vh]">
      <div class="text-center">
        <div class="w-16 h-16 mx-auto mb-4 rounded-full bg-blue-100 flex items-center justify-center">
          <svg class="w-8 h-8 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
          </svg>
        </div>
        <h2 class="text-xl font-bold text-gray-800 mb-2">请先登录</h2>
        <p class="text-gray-500 mb-6">登录后即可使用题库、刷题、模拟面试等功能</p>
        <button
          @click="showLoginModal = true"
          class="px-8 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition text-sm"
        >立即登录</button>
      </div>
    </div>

    <main v-else class="p-5 lg:p-8 max-w-[98%] mx-auto">
      <div class="grid grid-cols-1 lg:grid-cols-4 gap-8">
      <AnalyticsSidebar
        :analytics="analytics"
        :master-bank="masterBank"
        :popular-tags="popularTags"
        :selected-tag="selectedTag"
        :practice-stats="practiceStats"
        :recommend-seed="recommendSeed"
        @refresh="fetchAnalytics"
        @select-tag="onSelectTag($event)"
        @go-to-question="onGoToQuestion"
        @refresh-recommend="recommendSeed++"
      />

      <div class="lg:col-span-3 bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <TabBar :active-tab="activeTab" @update:active-tab="onTabChange" />

        <div class="p-3 lg:p-6">
          <SearchFilterBar
            v-if="activeTab === 'MasterBank'"
            :search-query="searchQuery"
            :filter-difficulty="filterDifficulty"
            :show-starred-only="showStarredOnly"
            :show-starred-toggle="activeTab === 'MasterBank'"
            @update:search-query="searchQuery = $event"
            @update:filter-difficulty="filterDifficulty = $event"
            @update:show-starred-only="showStarredOnly = $event"
          />

          <!-- Sub-tag filter chips -->
          <div v-if="activeTab === 'MasterBank' && selectedTag !== '全部' && availableSubTags.length > 0" class="flex flex-wrap gap-2 mb-4">
            <span class="text-xs text-gray-500 self-center mr-1">子标签：</span>
            <button
              v-for="st in availableSubTags"
              :key="st.tag"
              @click="toggleSubTag(st.tag)"
              class="text-xs px-2.5 py-1 rounded-full border transition-colors"
              :class="selectedSubTags.includes(st.tag)
                ? 'bg-green-100 text-green-700 border-green-300 font-semibold'
                : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50 hover:border-gray-300'"
            >
              {{ st.tag }}
              <span class="ml-1 text-xs opacity-60">{{ st.count }}</span>
            </button>
          </div>

          <!-- Action bar -->
          <div class="flex flex-wrap justify-between items-center mb-4 lg:mb-6 gap-2">
            <h2 class="text-lg lg:text-xl font-bold flex items-center gap-2">
              {{ activeTab === 'JD' ? 'JD 筛选' : activeTab === 'Interview' ? '面经记录' : activeTab === 'MockInterview' ? '题目抽测' : activeTab === 'Import' ? '导入数据' : activeTab === 'KnowledgeGraph' ? '知识图谱' : '高频题库' }}
              <span v-if="activeTab === 'MasterBank' && selectedTag !== '全部'" class="text-sm font-normal bg-green-100 text-green-700 px-3 py-1 rounded-full border border-green-200">
                筛选: {{ selectedTag }}
              </span>
            </h2>
            <div class="flex flex-wrap gap-2">
              <button v-if="activeTab === 'MasterBank'" @click="triggerBuildMasterBank" class="text-sm bg-purple-600 text-white font-bold px-4 py-2 rounded hover:bg-purple-700 transition">
                {{ isBuilding ? '重建中...' : '重建题库' }}
              </button>
              <button v-if="!isDataLoading && activeTab !== 'Import'" @click="fetchTableData" :disabled="isDataLoading" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed">
                {{ isDataLoading ? '加载中...' : '刷新数据' }}
              </button>
              <button v-if="activeTab === 'JD' || activeTab === 'Interview'" @click="downloadCSV" class="text-sm bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700">导出 CSV</button>
            </div>
          </div>

          <!-- Error banner -->
          <div v-if="dataLoadError" class="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg flex items-center justify-between">
            <span>{{ dataLoadError }}</span>
            <button @click="fetchTableData" class="text-sm bg-red-100 hover:bg-red-200 px-3 py-1 rounded transition">重试</button>
          </div>

          <!-- Loading skeleton -->
          <div v-if="isDataLoading && jdData.length === 0 && interviewData.length === 0 && masterBank.length === 0" class="py-10 text-center">
            <svg class="animate-spin h-8 w-8 text-blue-500 mx-auto mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
            <p class="text-gray-500">数据加载中...</p>
          </div>

          <!-- JD Tab -->
          <DataTable
            v-if="activeTab === 'JD'"
            :columns="jdColumns"
            :rows="jdData"
            :selected-count="jdSelection.selectedCount.value"
            :is-selected="(id) => jdSelection.selectedIds.value.has(id)"
            :batch-actions="jdBatchActions"
            @toggle-select-all="jdSelection.toggleSelectAll()"
            @invert-selection="jdSelection.invertSelection()"
            @toggle-item="jdSelection.toggleItem($event)"
          >
            <template #actions="{ row }">
              <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="row['来源链接']" target="_blank" class="text-blue-500 hover:underline mr-3">链接</a>
              <span v-else class="text-gray-300 mr-3">-</span>
              <button @click="deleteDataRow('jd', row.id)" class="text-red-500 hover:text-red-700 font-bold">删除</button>
            </template>
            <template #cell-company="{ row }">
              <InlineEdit :row="row" field="公司" db-column="company" table-name="jd" @save="saveField" />
            </template>
            <template #cell-job_title="{ row }">
              <InlineEdit :row="row" field="岗位名称" db-column="job_title" table-name="jd" @save="saveField" />
            </template>
            <template #cell-salary="{ row }">
              <span class="text-red-600">{{ row['薪资范围'] }}</span>
            </template>
            <template #cell-tech_stack="{ row }">
              <span class="whitespace-pre-wrap break-words min-w-[200px]">{{ row['核心技术要求'] }}</span>
            </template>
            <template #cell-bonus="{ row }">
              <span class="text-gray-500 whitespace-pre-wrap break-words">{{ row['加分项'] }}</span>
            </template>
          </DataTable>

          <!-- Interview Tab -->
          <div v-if="activeTab === 'Interview' && interviewSeasons.length > 0" class="flex items-center gap-2 mb-4">
            <label class="text-xs text-gray-500">招聘季筛选：</label>
            <select v-model="filterSeason" class="border border-gray-300 rounded-lg px-3 py-1.5 text-xs focus:ring-blue-500 focus:border-blue-500">
              <option value="">全部</option>
              <option v-for="s in interviewSeasons" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <DataTable
            v-if="activeTab === 'Interview'"
            :columns="interviewColumns"
            :rows="filteredInterviewData"
            :selected-count="interviewSelection.selectedCount.value"
            :is-selected="(id) => interviewSelection.selectedIds.value.has(id)"
            :batch-actions="interviewBatchActions"
            @toggle-select-all="interviewSelection.toggleSelectAll()"
            @invert-selection="interviewSelection.invertSelection()"
            @toggle-item="interviewSelection.toggleItem($event)"
          >
            <template #actions="{ row }">
              <button @click="reprocessInterview(row.id)" :disabled="reprocessingIds[row.id]" class="text-blue-500 hover:text-blue-700 font-bold mr-2 disabled:opacity-50" title="重新提取并打标">
                <svg v-if="reprocessingIds[row.id]" class="animate-spin inline-block w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                <span v-else>重新分析</span>
              </button>
              <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="row['来源链接']" target="_blank" class="text-blue-500 hover:underline mr-3">链接</a>
              <span v-else class="text-gray-300 mr-3">-</span>
              <button @click="deleteDataRow('interview', row.id)" class="text-red-500 hover:text-red-700 font-bold">删除</button>
            </template>
            <template #cell-company="{ row }">
              <InlineEdit :row="row" field="公司" db-column="company" table-name="interview" @save="saveField" />
            </template>
            <template #cell-round="{ row }">
              <InlineEdit :row="row" field="面试轮次" db-column="round" table-name="interview" @save="saveField" />
            </template>
            <template #cell-focus="{ row }">
              <InlineEdit :row="row" field="考察重点" db-column="focus" table-name="interview" type="textarea" @save="saveField" />
            </template>
            <template #cell-questions_list="{ row }">
              <InlineEdit :row="row" field="具体题目清单" db-column="questions_list" table-name="interview" type="textarea" rows="6" @save="saveField" />
            </template>
            <template #cell-difficulty="{ row }">
              <InlineEdit :row="row" field="难易程度" db-column="difficulty" table-name="interview" type="select" :options="['简单', '中等', '困难']" @save="saveField" />
            </template>
          </DataTable>

          <!-- MockInterview Tab -->
          <MockInterview
            v-if="activeTab === 'MockInterview'"
            ref="mockInterviewRef"
            :popular-tags="popularTags"
          />

          <!-- KnowledgeGraph Tab -->
          <KnowledgeGraph
            v-if="activeTab === 'KnowledgeGraph'"
            @filter-by-tag="onGraphFilterTag"
            @filter-by-category="onGraphFilterCategory"
          />

          <!-- Import Tab -->
          <StagingPanel v-if="activeTab === 'Import'" :active-season="activeSeason" @submitted="onSubmitted" />

          <!-- MasterBank Tab -->
          <MasterBankList
            v-if="activeTab === 'MasterBank'"
            :items="filteredMasterBank"
            :selected-count="masterSelection.selectedCount.value"
            :is-selected="(id) => masterSelection.selectedIds.value.has(id)"
            :batch-actions="masterBatchActions"
            @toggle-select-all="masterSelection.toggleSelectAll()"
            @invert-selection="masterSelection.invertSelection()"
            @toggle-item="masterSelection.toggleItem($event)"
            @toggle-star="toggleStar"
            @retag="retagQuestion"
            @generate-answer="generateAnswer"
            @save-field="saveFieldFromEvent"
            @expand-all="filteredMasterBank.forEach(q => q._showAnswer = true)"
            @collapse-all="filteredMasterBank.forEach(q => q._showAnswer = false)"
          />
        </div>
      </div>
    </div>
    </main>

    <ToastContainer />
    <ConfirmDialog />
    <LoginModal :visible="showLoginModal" @close="showLoginModal = false" @login-success="handleLoginSuccess" />
    <AdminReview :visible="showReviewPanel" @close="showReviewPanel = false" @reviewed="fetchTableData" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { cancelAllRequests, setUnauthorizedHandler, setAuthToken, refreshAuthToken } from './utils/http.js'
import * as api from './api/index.js'
import { useSelection } from './composables/useSelection.js'

import StagingPanel from './components/StagingPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import AnalyticsSidebar from './components/AnalyticsSidebar.vue'
import TabBar from './components/TabBar.vue'
import SearchFilterBar from './components/SearchFilterBar.vue'
import DataTable from './components/DataTable.vue'
import MasterBankList from './components/MasterBankList.vue'
import MockInterview from './components/MockInterview.vue'
import KnowledgeGraph from './components/KnowledgeGraph.vue'
import InlineEdit from './components/InlineEdit.vue'
import ToastContainer from './components/ToastContainer.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import LoginModal from './components/LoginModal.vue'
import UserMenu from './components/UserMenu.vue'
import AdminReview from './components/AdminReview.vue'
import { useToast, useConfirm } from './composables/useNotification.js'

const toast = useToast()
const { confirm: showConfirm } = useConfirm()

// ── State ──
const activeTab = ref('MasterBank')
const jdData = ref([])
const interviewData = ref([])
const masterBank = ref([])
const isBuilding = ref(false)
const isDataLoading = ref(false)
const dataLoadError = ref(null)
const analytics = ref({ tech_trends: {} })
const selectedTag = ref('全部')
const selectedSubTags = ref([])
const searchQuery = ref('')
const filterDifficulty = ref('')
const showStarredOnly = ref(false)
const filterSeason = ref('')
const reprocessingIds = ref({})
const mockInterviewRef = ref(null)
const activeSeason = ref('')
const showSettings = ref(false)
const practiceStats = ref({})
const recommendSeed = ref(0)

// ── Auth state ──
const currentUser = ref(null)
const showLoginModal = ref(false)
const showReviewPanel = ref(false)
const pendingReviewCount = ref(0)

// ── Selection composables ──
const jdSelection = useSelection(() => jdData.value)
const interviewSelection = useSelection(() => interviewData.value)
const masterSelection = useSelection(() => filteredMasterBank.value)

// ── Column definitions ──
const jdColumns = [
  { key: 'company', label: '公司', frontendKey: '公司' },
  { key: 'job_title', label: '岗位名称', frontendKey: '岗位名称' },
  { key: 'salary', label: '薪资范围', frontendKey: '薪资范围' },
  { key: 'tech_stack', label: '核心技术', frontendKey: '核心技术要求', cellClass: 'whitespace-pre-wrap break-words min-w-[200px]' },
  { key: 'bonus', label: '加分项', frontendKey: '加分项' }
]

const interviewColumns = [
  { key: 'company', label: '公司', frontendKey: '公司' },
  { key: 'round', label: '面试轮次', frontendKey: '面试轮次' },
  { key: 'focus', label: '考察重点', frontendKey: '考察重点', cellClass: 'whitespace-pre-wrap break-words min-w-[120px]' },
  { key: 'questions_list', label: '具体题目清单', frontendKey: '具体题目清单', cellClass: 'whitespace-pre-wrap break-words min-w-[300px]' },
  { key: 'difficulty', label: '难度', frontendKey: '难易程度' },
  { key: 'season', label: '招聘季', frontendKey: 'season' }
]

// ── Computed ──
const popularTags = computed(() => {
  const counts = {}
  masterBank.value.forEach(q => {
    const cats = (q.cat1 || '未分类').split(',').map(c => c.trim()).filter(c => c)
    if (cats.length === 0) counts['未分类'] = (counts['未分类'] || 0) + 1
    else cats.forEach(cat => counts[cat] = (counts[cat] || 0) + 1)
  })
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).reduce((acc, [k, v]) => { acc[k] = v; return acc }, {})
})

const availableSubTags = computed(() => {
  if (selectedTag.value === '全部') return []
  const catItems = masterBank.value.filter(q =>
    (q.cat1 || '未分类').split(',').map(c => c.trim()).includes(selectedTag.value)
  )
  const counts = {}
  catItems.forEach(q => {
    const tags = (q.tags || '').split(',').map(t => t.trim()).filter(t => t)
    tags.forEach(tag => { counts[tag] = (counts[tag] || 0) + 1 })
  })
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([tag, count]) => ({ tag, count }))
})

const filteredMasterBank = computed(() => {
  let result = masterBank.value
  if (selectedTag.value !== '全部') {
    result = result.filter(q => (q.cat1 || '未分类').split(',').map(c => c.trim()).includes(selectedTag.value))
  }
  if (selectedSubTags.value.length > 0) {
    result = result.filter(q => {
      const itemTags = (q.tags || '').split(',').map(t => t.trim()).filter(t => t)
      return selectedSubTags.value.some(st => itemTags.includes(st))
    })
  }
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.trim().toLowerCase()
    result = result.filter(q => (q.question || '').toLowerCase().includes(query) || (q.cat1 || '').toLowerCase().includes(query) || (q.tags || '').toLowerCase().includes(query))
  }
  if (filterDifficulty.value) result = result.filter(q => (q.difficulty || '').includes(filterDifficulty.value))
  if (showStarredOnly.value) result = result.filter(q => q.is_starred)
  return result
})

const interviewSeasons = computed(() => {
  const seasons = [...new Set(interviewData.value.map(d => d.season).filter(Boolean))]
  return seasons.sort()
})

const filteredInterviewData = computed(() => {
  if (!filterSeason.value) return interviewData.value
  return interviewData.value.filter(d => d.season === filterSeason.value)
})

// Refresh practice stats when returning from mock interview
watch(activeTab, (newTab, oldTab) => {
  if (oldTab === 'MockInterview' && newTab === 'MasterBank') {
    fetchPracticeStats()
  }
})

// ── Batch action definitions ──
const jdBatchActions = computed(() => [
  {
    key: 'batch-delete',
    label: '批量删除',
    color: 'red',
    handler: async (onProgress) => {
      const ids = [...jdSelection.selectedIds.value]
      if (!await showConfirm(`确定要删除选中的 ${ids.length} 条记录？`)) return
      onProgress(0, ids.length)
      try {
        const result = await api.batchDeleteData('jd', ids)
        onProgress(result.deleted, ids.length)
        toast.success(`已成功删除 ${result.deleted} 条记录！`)
      } catch (e) { toast.error(`批量删除失败: ${e.message}`) }
      jdSelection.clearSelection()
      fetchTableData()
      fetchAnalytics()
    }
  }
])

const interviewBatchActions = computed(() => [
  {
    key: 'batch-reprocess',
    label: '批量重新分析',
    color: 'blue',
    handler: async (onProgress) => {
      const ids = [...interviewSelection.selectedIds.value]
      if (!await showConfirm(`确定要重新分析选中的 ${ids.length} 条面经？`)) return
      onProgress(0, ids.length)
      let ok = 0
      for (let i = 0; i < ids.length; i++) {
        try { await api.reprocessInterview(ids[i]); ok++ } catch (e) { console.error(e) }
        onProgress(i + 1, ids.length)
      }
      toast.success(`批量重新分析完成，成功解析 ${ok} 条记录！`)
      interviewSelection.clearSelection()
      fetchTableData()
      fetchAnalytics()
    }
  },
  {
    key: 'batch-delete',
    label: '批量删除',
    color: 'red',
    handler: async (onProgress) => {
      const ids = [...interviewSelection.selectedIds.value]
      if (!await showConfirm(`确定要删除选中的 ${ids.length} 条记录？`)) return
      onProgress(0, ids.length)
      try {
        const result = await api.batchDeleteData('interview', ids)
        onProgress(result.deleted, ids.length)
        toast.success(`已成功删除 ${result.deleted} 条记录！`)
      } catch (e) { toast.error(`批量删除失败: ${e.message}`) }
      interviewSelection.clearSelection()
      fetchTableData()
      fetchAnalytics()
    }
  }
])

const masterBatchActions = computed(() => [
  {
    key: 'batch-generate',
    label: '批量生成答案',
    color: 'blue',
    handler: async (onProgress) => {
      const ids = [...masterSelection.selectedIds.value]
      if (!await showConfirm(`确定要为选中的 ${ids.length} 道题目生成答案？`)) return
      try {
        const result = await api.batchGenerateAnswers(ids, (event) => {
          if (event.type === 'init') {
            if (event.total === 0) {
              toast.info(`所有 ${event.skipped} 道题目已有答案，无需生成`)
            } else {
              onProgress(0, event.total)
            }
          } else if (event.type === 'progress') {
            onProgress(event.current, event.total)
          }
        })
        if (result) {
          const parts = []
          if (result.generated) parts.push(`成功 ${result.generated} 题`)
          if (result.failed) parts.push(`失败 ${result.failed} 题`)
          if (result.skipped) parts.push(`跳过 ${result.skipped} 题`)
          toast.success(parts.length ? `生成完成：${parts.join('，')}` : '生成完成')
        }
      } catch (e) { toast.error(`批量生成答案失败: ${e.message}`) }
      fetchTableData()
    }
  },
  {
    key: 'batch-delete',
    label: '批量删除',
    color: 'red',
    handler: async (onProgress) => {
      const ids = [...masterSelection.selectedIds.value]
      if (!await showConfirm(`确定要删除选中的 ${ids.length} 道题目？`)) return
      onProgress(0, ids.length)
      try {
        const result = await api.batchDeleteMasterBank(ids)
        onProgress(result.deleted, ids.length)
        toast.success(`已成功删除 ${result.deleted} 道题目！`)
      } catch (e) { toast.error(`批量删除失败: ${e.message}`) }
      fetchTableData()
    }
  }
])

// ── Data fetching ──
const fetchTableData = async () => {
  isDataLoading.value = true
  dataLoadError.value = null
  try {
    const [jdResp, intResp, masterResp] = await Promise.all([
      api.fetchJdData(),
      api.fetchInterviewData(),
      api.fetchMasterBank()
    ])
    jdData.value = (jdResp.items || jdResp).map(item => ({ ...item }))
    interviewData.value = (intResp.items || intResp).map(item => ({ ...item }))
    masterBank.value = (masterResp.items || masterResp).map(q => ({ ...q, _showAnswer: false, _isLoadingAnswer: false, _isRetagging: false, _isEditingAnswer: false, _editAnswer: '' }))
    selectedSubTags.value = []
    jdSelection.clearSelection()
    interviewSelection.clearSelection()
  } catch (e) {
    dataLoadError.value = e.message || '数据加载失败，请刷新重试'
  } finally {
    isDataLoading.value = false
  }
}

const fetchAnalytics = async () => {
  try { analytics.value = await api.fetchAnalytics() } catch (e) { console.error('获取分析数据失败', e) }
}

const fetchPracticeStats = async () => {
  try { practiceStats.value = await api.fetchPracticeStats() } catch (e) { console.error('获取练习统计失败', e) }
}

// ── Actions ──
const onSubmitted = () => {
  activeTab.value = 'MasterBank'
  fetchTableData()
  fetchAnalytics()
}

const onTabChange = (tab) => {
  activeTab.value = tab
}

const onSelectTag = (tag) => {
  selectedTag.value = tag
  selectedSubTags.value = []
  activeTab.value = 'MasterBank'
}

const onGraphFilterTag = (tagName) => {
  selectedTag.value = '全部'
  selectedSubTags.value = []
  searchQuery.value = tagName
  activeTab.value = 'MasterBank'
}

const onGraphFilterCategory = (catName) => {
  selectedTag.value = catName
  selectedSubTags.value = []
  searchQuery.value = ''
  activeTab.value = 'MasterBank'
}

const onGoToQuestion = (question) => {
  activeTab.value = 'MasterBank'
  // Set search to the question text (truncated for a reasonable search)
  const q = question.question || ''
  searchQuery.value = q.length > 30 ? q.substring(0, 30) : q
  selectedTag.value = '全部'
  selectedSubTags.value = []
}

const toggleSubTag = (tag) => {
  const idx = selectedSubTags.value.indexOf(tag)
  if (idx === -1) {
    selectedSubTags.value = [...selectedSubTags.value, tag]
  } else {
    selectedSubTags.value = selectedSubTags.value.filter(t => t !== tag)
  }
}

const deleteDataRow = async (type, recordId) => {
  if (!await showConfirm('确定要删除该记录？')) return
  try {
    await api.deleteRecord(type, recordId)
    toast.success('删除成功')
    fetchTableData()
    fetchAnalytics()
  } catch (err) { toast.error(`删除失败: ${err.message}`) }
}

const reprocessInterview = async (id) => {
  if (!await showConfirm('确定要重新解析该面经？')) return
  reprocessingIds.value[id] = true
  try {
    const data = await api.reprocessInterview(id)
    toast.success('重新解析完成')
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error(`失败：${e.message}`) }
  finally { reprocessingIds.value[id] = false }
}

const retagQuestion = async (question) => {
  if (!await showConfirm('确定要重新分类该题目？')) return
  question._isRetagging = true
  try {
    const data = await api.retagQuestion(question.id)
    question.cat1 = data.data.cat1
    question.cat2 = data.data.cat2
    question.tags = data.data.tags
    question.difficulty = data.data.difficulty
    toast.success('分类成功')
    fetchAnalytics()
  } catch (e) { toast.error(`失败：${e.message}`) }
  finally { question._isRetagging = false }
}

const saveField = async (tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey) => {
  try {
    await api.updateRecord({ table_name: tableName, record_id: recordId, update_data: { [dbColumn]: newValue } })
    rowObj[frontendKey] = newValue
    rowObj[editStateKey] = false
    toast.success('保存成功')
  } catch (err) { toast.error(`保存失败: ${err.message}`) }
}

const saveFieldFromEvent = ({ tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey }) => {
  saveField(tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey)
}

const toggleStar = async (question) => {
  try {
    const data = await api.toggleStar(question.id)
    question.is_starred = data.is_starred
  } catch (e) { toast.error(`操作失败：${e.message}`) }
}

const generateAnswer = async (question) => {
  question._isLoadingAnswer = true
  try {
    const data = await api.generateAnswer(question.id)
    question.ai_answer = data.answer
    toast.success('答案生成成功')
  } catch (e) { toast.error(`生成失败：${e.message}`) }
  finally { question._isLoadingAnswer = false }
}

const triggerBuildMasterBank = async () => {
  if (!await showConfirm('将重新整理全部题目，确定继续？')) return
  isBuilding.value = true
  try {
    const data = await api.buildMasterBank()
    toast.success(`重建完成，共 ${data.total_unique} 道题目`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('重建失败：' + e.message) }
  finally { isBuilding.value = false }
}

const downloadCSV = () => { window.open(api.getDownloadUrl(activeTab.value.toLowerCase()), '_blank') }

// ── Lifecycle ──
const initAuth = async () => {
  // 尝试用 HttpOnly refresh cookie 自动恢复登录状态
  const refreshResult = await refreshAuthToken()
  if (refreshResult?.token && refreshResult?.user) {
    setAuthToken(refreshResult.token)
    currentUser.value = refreshResult.user
    loadAllData()
    loadPendingCount()
  } else {
    showLoginModal.value = true
  }
}

const handleLoginSuccess = (user) => {
  // access token 已由 LoginModal 调用 setAuthToken 存入内存
  currentUser.value = user
  loadAllData()
  loadPendingCount()
}

const handleLogout = () => {
  setAuthToken('')
  currentUser.value = null
  fetchTableData()
  fetchPracticeStats()
  pendingReviewCount.value = 0
}

const handleBankModeChanged = (user) => {
  currentUser.value = user
  fetchTableData()
  fetchPracticeStats()
}

const loadPendingCount = async () => {
  if (!currentUser.value?.is_admin) { pendingReviewCount.value = 0; return }
  try {
    const data = await api.fetchPendingQuestions()
    pendingReviewCount.value = data.total || 0
  } catch { pendingReviewCount.value = 0 }
}

// Register 401 handler
setUnauthorizedHandler(() => {
  showLoginModal.value = true
})

const loadAllData = () => {
  fetchTableData()
  fetchAnalytics()
  fetchPracticeStats()
}

onMounted(async () => {
  await initAuth()
})
onUnmounted(() => cancelAllRequests())
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background-color: #cbd5e1; border-radius: 20px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background-color: #94a3b8; }

:deep(pre) { background-color: #1e293b; color: #f8fafc; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; margin-top: 0.5rem; margin-bottom: 1rem; }
:deep(code) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.875em; }
:deep(p code) { background-color: #e2e8f0; color: #c53030; padding: 0.125rem 0.25rem; border-radius: 0.25rem; }
:deep(ul) { list-style-type: disc; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(ol) { list-style-type: decimal; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(strong) { font-weight: 700; color: #111827; }
:deep(h1), :deep(h2), :deep(h3) { font-weight: 700; color: #111827; margin-top: 1.5rem; margin-bottom: 0.5rem; }
:deep(h3) { font-size: 1.125rem; }
</style>

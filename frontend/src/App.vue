<template>
  <div class="min-h-screen p-3 lg:p-8 max-w-[98%] mx-auto bg-slate-50">
    <header class="mb-6 lg:mb-10 text-center">
      <h1 class="text-2xl lg:text-4xl font-bold text-gray-900 mb-2">多模态 JD 与面经智能解析系统</h1>
      <p class="text-sm lg:text-base text-gray-500">将零散的内容放至暂存区，确认无误后一键提交解析与增量聚类</p>
    </header>

    <StagingPanel @submitted="onSubmitted" />

    <div class="grid grid-cols-1 lg:grid-cols-4 gap-8">
      <AnalyticsSidebar
        :analytics="analytics"
        :master-bank="masterBank"
        :popular-tags="popularTags"
        :selected-tag="selectedTag"
        @refresh="fetchAnalytics"
        @select-tag="selectedTag = $event"
      />

      <div class="lg:col-span-3 bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <TabBar :active-tab="activeTab" @update:active-tab="onTabChange" />

        <div class="p-3 lg:p-6">
          <SearchFilterBar
            v-if="activeTab === 'MasterBank' || activeTab === 'MockInterview'"
            :search-query="searchQuery"
            :filter-difficulty="filterDifficulty"
            :show-starred-only="showStarredOnly"
            :show-starred-toggle="activeTab === 'MasterBank'"
            @update:search-query="searchQuery = $event"
            @update:filter-difficulty="filterDifficulty = $event"
            @update:show-starred-only="showStarredOnly = $event"
          />

          <!-- Action bar -->
          <div class="flex flex-wrap justify-between items-center mb-4 lg:mb-6 gap-2">
            <h2 class="text-lg lg:text-xl font-bold flex items-center gap-2">
              {{ activeTab === 'JD' ? '职位描述库' : activeTab === 'Interview' ? '原始面经流水' : activeTab === 'MockInterview' ? '模拟面试' : '必考真题库' }}
              <span v-if="activeTab === 'MasterBank' && selectedTag !== '全部'" class="text-sm font-normal bg-green-100 text-green-700 px-3 py-1 rounded-full border border-green-200">
                分类筛选: {{ selectedTag }}
              </span>
            </h2>
            <div class="flex flex-wrap gap-2">
              <button v-if="activeTab === 'MasterBank'" @click="triggerBuildMasterBank" class="text-sm bg-purple-600 text-white font-bold px-4 py-2 rounded hover:bg-purple-700 transition">
                {{ isBuilding ? '正在提取全量特征并聚类去重...' : '全量重新计算题库排序' }}
              </button>
              <button @click="fetchTableData" :disabled="isDataLoading" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed">
                {{ isDataLoading ? '加载中...' : '刷新数据' }}
              </button>
              <button v-if="activeTab === 'JD' || activeTab === 'Interview'" @click="downloadCSV" class="text-sm bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700">一键导出 CSV</button>
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
            @toggle-select-all="jdSelection.toggleSelectAll()"
            @invert-selection="jdSelection.invertSelection()"
            @batch-delete="batchDeleteData('jd', jdData, jdSelection)"
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
          <DataTable
            v-if="activeTab === 'Interview'"
            :columns="interviewColumns"
            :rows="interviewData"
            :selected-count="interviewSelection.selectedCount.value"
            :is-selected="(id) => interviewSelection.selectedIds.value.has(id)"
            @toggle-select-all="interviewSelection.toggleSelectAll()"
            @invert-selection="interviewSelection.invertSelection()"
            @batch-delete="batchDeleteData('interview', interviewData, interviewSelection)"
            @toggle-item="interviewSelection.toggleItem($event)"
          >
            <template #batch-actions>
              <button @click="batchReprocessInterview" :disabled="interviewSelection.selectedCount.value === 0" class="text-sm bg-blue-100 text-blue-700 px-3 py-1.5 rounded hover:bg-blue-200 transition font-medium disabled:opacity-50 disabled:cursor-not-allowed">
                批量重新分析 ({{ interviewSelection.selectedCount.value }})
              </button>
            </template>
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
            :filter-difficulty="filterDifficulty"
          />

          <!-- MasterBank Tab -->
          <MasterBankList
            v-if="activeTab === 'MasterBank'"
            :items="filteredMasterBank"
            :selected-count="masterSelection.selectedCount.value"
            :is-selected="(id) => masterSelection.selectedIds.value.has(id)"
            @toggle-select-all="masterSelection.toggleSelectAll()"
            @invert-selection="masterSelection.invertSelection()"
            @toggle-item="masterSelection.toggleItem($event)"
            @batch-generate="batchGenerateAnswers"
            @batch-delete="batchDeleteMasterBank"
            @toggle-star="toggleStar"
            @retag="retagQuestion"
            @generate-answer="generateAnswer"
            @save-field="saveFieldFromEvent"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { cancelAllRequests } from './utils/http.js'
import * as api from './api/index.js'
import { useSelection } from './composables/useSelection.js'

import StagingPanel from './components/StagingPanel.vue'
import AnalyticsSidebar from './components/AnalyticsSidebar.vue'
import TabBar from './components/TabBar.vue'
import SearchFilterBar from './components/SearchFilterBar.vue'
import DataTable from './components/DataTable.vue'
import MasterBankList from './components/MasterBankList.vue'
import MockInterview from './components/MockInterview.vue'
import InlineEdit from './components/InlineEdit.vue'

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
const searchQuery = ref('')
const filterDifficulty = ref('')
const showStarredOnly = ref(false)
const reprocessingIds = ref({})
const mockInterviewRef = ref(null)

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
  { key: 'difficulty', label: '难度', frontendKey: '难易程度' }
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

const filteredMasterBank = computed(() => {
  let result = masterBank.value
  if (selectedTag.value !== '全部') {
    result = result.filter(q => (q.cat1 || '未分类').split(',').map(c => c.trim()).includes(selectedTag.value))
  }
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.trim().toLowerCase()
    result = result.filter(q => (q.question || '').toLowerCase().includes(query) || (q.cat1 || '').toLowerCase().includes(query) || (q.tags || '').toLowerCase().includes(query))
  }
  if (filterDifficulty.value) result = result.filter(q => (q.difficulty || '').includes(filterDifficulty.value))
  if (showStarredOnly.value) result = result.filter(q => q.is_starred)
  return result
})

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

// ── Actions ──
const onSubmitted = () => {
  activeTab.value = 'MasterBank'
  fetchTableData()
  fetchAnalytics()
}

const onTabChange = (tab) => {
  activeTab.value = tab
}

const deleteDataRow = async (type, recordId) => {
  if (!confirm('确定要彻底删除这一行记录吗？此操作不可恢复！')) return
  try {
    await api.deleteRecord(type, recordId)
    fetchTableData()
    fetchAnalytics()
  } catch (err) { alert(`删除失败: ${err.message}`) }
}

const batchDeleteData = async (type, dataList, selection) => {
  const ids = dataList.filter(item => selection.selectedIds.value.has(item.id)).map(item => item.id)
  if (ids.length === 0) return
  if (!confirm(`确定要彻底删除选中的 ${ids.length} 行记录吗？此操作不可恢复！`)) return
  let ok = 0
  for (const id of ids) { try { await api.deleteRecord(type, id); ok++ } catch (e) { console.error(`删除 ID:${id} 失败`, e) } }
  alert(`已成功删除 ${ok} 条记录！`)
  selection.clearSelection()
  fetchTableData()
  fetchAnalytics()
}

const reprocessInterview = async (id) => {
  if (!confirm('确定要重新调用大模型提取并打标该面经记录吗？')) return
  reprocessingIds.value[id] = true
  try {
    const data = await api.reprocessInterview(id)
    alert(data.message)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { alert(`错误: ${e.message}`) }
  finally { reprocessingIds.value[id] = false }
}

const batchReprocessInterview = async () => {
  const targets = interviewData.value.filter(item => interviewSelection.selectedIds.value.has(item.id) && !reprocessingIds.value[item.id])
  if (targets.length === 0) return
  if (!confirm(`确定要为选中的 ${targets.length} 条面经记录排队重新分析吗？`)) return
  let ok = 0
  for (const item of targets) {
    reprocessingIds.value[item.id] = true
    try { await api.reprocessInterview(item.id); ok++ } catch (e) { console.error(`重新解析面经ID ${item.id} 失败`, e) }
    finally { reprocessingIds.value[item.id] = false }
  }
  alert(`批量重新分析完成，成功解析 ${ok} 条记录！`)
  fetchTableData()
  fetchAnalytics()
}

const retagQuestion = async (question) => {
  if (!confirm('确定要重新调用大模型对该题目进行结构化打标吗？')) return
  question._isRetagging = true
  try {
    const data = await api.retagQuestion(question.id)
    question.cat1 = data.data.cat1
    question.cat2 = data.data.cat2
    question.tags = data.data.tags
    question.difficulty = data.data.difficulty
    fetchAnalytics()
  } catch (e) { alert(`错误: ${e.message}`) }
  finally { question._isRetagging = false }
}

const saveField = async (tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey) => {
  try {
    await api.updateRecord({ table_name: tableName, record_id: recordId, update_data: { [dbColumn]: newValue } })
    rowObj[frontendKey] = newValue
    rowObj[editStateKey] = false
  } catch (err) { alert(`系统错误: ${err.message}`) }
}

const saveFieldFromEvent = ({ tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey }) => {
  saveField(tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey)
}

const toggleStar = async (question) => {
  try {
    const data = await api.toggleStar(question.id)
    question.is_starred = data.is_starred
  } catch (e) { alert(`收藏操作失败: ${e.message}`) }
}

const generateAnswer = async (question) => {
  question._isLoadingAnswer = true
  try {
    const data = await api.generateAnswer(question.id)
    question.ai_answer = data.answer
  } catch (e) { alert(`生成解答失败: ${e.message}`) }
  finally { question._isLoadingAnswer = false }
}

const batchGenerateAnswers = async () => {
  const sel = masterSelection.selectedIds.value
  const targets = filteredMasterBank.value.filter(q => sel.has(q.id) && !q._isLoadingAnswer)
  if (targets.length === 0) { alert('当前没有选中任何题目！'); return }
  if (!confirm(`确定要为 ${targets.length} 道选中题目排队生成答案吗？`)) return
  for (const q of targets) await generateAnswer(q)
  alert('批量生成解答完成！')
}

const batchDeleteMasterBank = async () => {
  const sel = masterSelection.selectedIds.value
  const targets = filteredMasterBank.value.filter(q => sel.has(q.id))
  if (targets.length === 0) return
  if (!confirm(`确定要彻底删除这 ${targets.length} 道高频真题吗？此操作不可恢复！`)) return
  let ok = 0
  for (const q of targets) { try { await api.deleteMasterQuestion(q.id); ok++ } catch (e) { console.error(`删除 ID:${q.id} 失败`, e) } }
  alert(`已成功删除 ${ok} 道题目！`)
  fetchTableData()
}

const triggerBuildMasterBank = async () => {
  if (!confirm('这将调用 Embeddings API 对所有题目进行重新聚类。确定继续吗？')) return
  isBuilding.value = true
  try {
    const data = await api.buildMasterBank()
    alert(`全量聚类计算完毕！共归纳出 ${data.total_unique} 道核心真题。`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { alert('计算失败：' + e.message) }
  finally { isBuilding.value = false }
}

const downloadCSV = () => { window.open(api.getDownloadUrl(activeTab.value.toLowerCase()), '_blank') }

// ── Lifecycle ──
onMounted(() => { fetchTableData(); fetchAnalytics() })
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

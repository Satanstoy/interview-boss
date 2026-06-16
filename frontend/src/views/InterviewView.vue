<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar" style="position: relative;">
    <!-- 页头 -->
    <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
      <div class="border-b border-border px-5 py-4">
        <div class="flex items-center gap-3">
          <div class="size-9 rounded-xl bg-gradient-brand flex items-center justify-center shadow-sm">
            <FileText class="size-5 text-white" />
          </div>
          <div>
            <h3 class="text-sm font-bold text-foreground">面经库</h3>
            <p class="text-caption text-muted-foreground">浏览和管理面试经验数据</p>
          </div>
        </div>
      </div>
    </div>
    <!-- Season filter bar -->
    <div class="flex items-center gap-2 mb-3 p-3 rounded-xl border border-border bg-card shadow-sm">
      <template v-if="interviewSeasons.length > 0">
        <label class="text-xs text-muted-foreground">招聘季筛选：</label>
        <Select v-model="filterSeason">
          <SelectTrigger class="min-w-[100px] h-8 text-xs">
            <SelectValue placeholder="全部" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">全部</SelectItem>
            <SelectItem v-for="s in interviewSeasons" :key="s" :value="s">{{ s }}</SelectItem>
          </SelectContent>
        </Select>
        <span class="text-muted-foreground/50 dark:text-muted-foreground">|</span>
      </template>
      <button
        @click="interviewSortOrder = interviewSortOrder === 'desc' ? 'asc' : 'desc'"
        class="inline-flex items-center gap-1 border border-border rounded-lg px-3 py-1.5 text-xs bg-card text-foreground hover:bg-muted dark:hover:bg-muted transition-colors"
        :title="interviewSortOrder === 'desc' ? '当前：最新在前，点击切换' : '当前：最旧在前，点击切换'"
      >
        <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path v-if="interviewSortOrder === 'desc'" stroke-linecap="round" stroke-linejoin="round" d="M3 4h13M3 8h9M3 12h5m4 0l4-4m0 0l4 4m-4-4v12" />
          <path v-else stroke-linecap="round" stroke-linejoin="round" d="M3 4h13M3 8h9m-9 4h9m5-4v12m0 0l-4-4m4 4l4-4" />
        </svg>
        上传日期 {{ interviewSortOrder === 'desc' ? '↓' : '↑' }}
      </button>
    </div>

    <!-- Interview DataTable -->
    <InterviewDataTable
      :columns="interviewColumns"
      :rows="filteredInterviewData"
      :selected-count="interviewSelection.selectedCount.value"
      :is-selected="(id) => interviewSelection.selectedIds.value.has(id)"
      :batch-actions="interviewBatchActions"
      :current-page="interviewCurrentPage"
      :page-size="interviewPageSize"
      :highlight-id="highlightInterviewId"
      @toggle-select-all="interviewSelection.toggleSelectAll()"
      @invert-selection="interviewSelection.invertSelection()"
      @toggle-item="interviewSelection.toggleItem($event)"
      @update:current-page="interviewCurrentPage = $event"
      @update:page-size="interviewPageSize = $event"
    >
      <template #actions="{ row }">
        <div class="flex items-center justify-center gap-1">
          <div v-if="displayUser?.is_admin" class="relative flex flex-col items-center">
            <button @click="reprocessInterview(row.id)" :disabled="reprocessingIds[row.id]" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 disabled:opacity-50 transition-colors duration-200" title="重新提取并打标">
              <svg v-if="reprocessingIds[row.id]" class="animate-spin size-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
              <svg v-else class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              <span class="text-[10px] leading-tight">{{ reprocessingIds[row.id] ? (reprocessProgress[row.id]?.step === 'tag' ? '标注中' : reprocessProgress[row.id]?.step === 'match' ? '聚类中' : reprocessProgress[row.id]?.step === 'save' ? '保存中' : '分析中') : '分析' }}</span>
            </button>
          </div>
          <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="safeUrl(row['来源链接'])" target="_blank" rel="noopener noreferrer" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 transition-colors duration-200" title="打开链接">
            <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
            <span class="text-[10px] leading-tight">链接</span>
          </a>
          <button v-if="displayUser?.is_admin || row.owner_id === displayUser?.id" @click="deleteDataRow('interview', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1 transition-colors duration-200" title="删除">
            <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
            <span class="text-[10px] leading-tight">删除</span>
          </button>
        </div>
      </template>
      <template #cell-company="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="公司" db-column="company" table-name="interview" @save="saveField" />
        <span v-else>{{ row['公司'] }}</span>
      </template>
      <template #cell-season="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="season" db-column="season" table-name="interview" @save="saveField" />
        <span v-else>{{ row['season'] }}</span>
      </template>
      <template #cell-round="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="面试轮次" db-column="round" table-name="interview" @save="saveField" />
        <span v-else>{{ row['面试轮次'] }}</span>
      </template>
      <template #cell-focus="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="考察重点" db-column="focus" table-name="interview" type="textarea" @save="saveField" />
        <span v-else>{{ row['考察重点'] }}</span>
      </template>
      <template #cell-questions_list="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="具体题目清单" db-column="questions_list" table-name="interview" type="textarea" rows="6" @save="saveField" />
        <span v-else>{{ row['具体题目清单'] }}</span>
      </template>
      <template #cell-difficulty="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="难易程度" db-column="difficulty" table-name="interview" type="select" :options="['简单', '中等', '困难']" @save="saveField" />
        <span v-else>{{ row['难易程度'] }}</span>
      </template>
      <template #cell-created_at="{ row }">
        <span class="text-xs text-muted-foreground whitespace-nowrap">{{ formatDate(row.created_at) }}</span>
      </template>
    </InterviewDataTable>

    <!-- Floating return button -->
    <button
      v-if="returnTab && highlightInterviewId"
      ref="floatingReturnBtn"
      @click="handleReturn"
      class="absolute z-50 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-primary-600 hover:bg-primary-700 dark:bg-primary-500 dark:hover:bg-primary-600 rounded-lg shadow-lg hover:shadow-xl transition-all duration-200 whitespace-nowrap"
      :style="floatingBtnStyle"
    >
      <svg class="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18"/></svg>
      {{ returnToPracticeMode ? '返回刷题模式' : '返回题库' }}
    </button>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { FileText } from '@lucide/vue'
import DataTable from '@/components/common/DataTable.vue'
import InlineEdit from '@/components/common/InlineEdit.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const InterviewDataTable = DataTable

const {
  filteredInterviewData, interviewSelection, interviewBatchActions,
  interviewCurrentPage, interviewPageSize,
  filterSeason, interviewSortOrder, interviewSeasons,
  highlightInterviewId, displayUser, safeUrl,
  saveField, deleteDataRow, reprocessInterview,
  reprocessingIds, reprocessProgress,
  returnTab, handleReturn, floatingReturnBtn, floatingBtnStyle,
  returnToPracticeMode, formatDate,
} = inject('appData')

const interviewColumns = [
  { key: 'company', label: '公司', frontendKey: '公司', width: '10%' },
  { key: 'season', label: '招聘季', frontendKey: 'season', width: '8%' },
  { key: 'round', label: '面试轮次', frontendKey: '面试轮次', width: '8%' },
  { key: 'focus', label: '考察重点', frontendKey: '考察重点', width: '14%', cellClass: 'whitespace-pre-wrap' },
  { key: 'questions_list', label: '具体题目清单', frontendKey: '具体题目清单', width: '32%', cellClass: 'whitespace-pre-wrap' },
  { key: 'difficulty', label: '难度', frontendKey: '难易程度', width: '8%' },
  { key: 'created_at', label: '上传日期', frontendKey: '上传日期', width: '10%' },
]
</script>

<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <JdDataTable
      :columns="jdColumns"
      :rows="jdData"
      :selected-count="jdSelection.selectedCount.value"
      :is-selected="(id) => jdSelection.selectedIds.value.has(id)"
      :batch-actions="jdBatchActions"
      :current-page="jdCurrentPage"
      :page-size="jdPageSize"
      @toggle-select-all="jdSelection.toggleSelectAll()"
      @invert-selection="jdSelection.invertSelection()"
      @toggle-item="jdSelection.toggleItem($event)"
      @update:current-page="jdCurrentPage = $event"
      @update:page-size="jdPageSize = $event"
    >
      <template #actions="{ row }">
        <div class="flex items-center justify-center gap-1">
          <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="safeUrl(row['来源链接'])" target="_blank" rel="noopener noreferrer" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 transition-colors duration-200" title="打开链接">
            <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
            <span class="text-[10px] leading-tight">链接</span>
          </a>
          <button v-if="displayUser?.is_admin || row.owner_id === displayUser?.id" @click="deleteDataRow('jd', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1 transition-colors duration-200" title="删除">
            <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
            <span class="text-[10px] leading-tight">删除</span>
          </button>
        </div>
      </template>
      <template #cell-company="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="公司" db-column="company" table-name="jd" @save="saveField" />
        <span v-else>{{ row['公司'] }}</span>
      </template>
      <template #cell-job_title="{ row }">
        <InlineEdit v-if="displayUser?.is_admin" :row="row" field="岗位名称" db-column="job_title" table-name="jd" @save="saveField" />
        <span v-else>{{ row['岗位名称'] }}</span>
      </template>
      <template #cell-salary="{ row }">
        <span class="text-red-600 dark:text-red-400 font-medium">{{ row['薪资范围'] }}</span>
      </template>
      <template #cell-tech_stack="{ row }">
        <span class="whitespace-pre-wrap break-words min-w-[200px]">{{ row['核心技术要求'] }}</span>
      </template>
      <template #cell-bonus="{ row }">
        <span class="text-gray-500 dark:text-gray-400 whitespace-pre-wrap break-words">{{ row['加分项'] }}</span>
      </template>
    </JdDataTable>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import DataTable from '@/components/common/DataTable.vue'
import InlineEdit from '@/components/common/InlineEdit.vue'

// Alias to avoid collision with possible native table element names
const JdDataTable = DataTable

const {
  jdData, displayUser,
  jdSelection, jdBatchActions,
  jdCurrentPage, jdPageSize,
  safeUrl, saveField, deleteDataRow,
} = inject('appData')

const jdColumns = [
  { key: 'company', label: '公司', frontendKey: '公司', width: '12%' },
  { key: 'job_title', label: '岗位名称', frontendKey: '岗位名称', width: '15%' },
  { key: 'salary', label: '薪资范围', frontendKey: '薪资范围', width: '10%' },
  { key: 'tech_stack', label: '核心技术', frontendKey: '核心技术要求', width: '28%', cellClass: 'whitespace-pre-wrap' },
  { key: 'bonus', label: '加分项', frontendKey: '加分项', width: '22%' },
  { key: 'season', label: '招聘季', frontendKey: 'season', width: '8%' },
]
</script>

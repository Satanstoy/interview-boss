<template>
  <div class="flex flex-1 min-h-0 flex-col gap-2 overflow-y-auto px-2 py-2 custom-scrollbar sm:gap-4 sm:px-4 sm:py-4 md:px-6 md:py-6">
    <!-- 页头 -->
    <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
      <div class="border-b border-border px-5 py-4">
        <div class="flex items-center gap-3">
          <div class="size-9 rounded-xl bg-gradient-brand flex items-center justify-center shadow-sm">
            <Briefcase class="size-5 text-white" />
          </div>
          <div>
            <h3 class="text-sm font-bold text-foreground">JD 库</h3>
            <p class="text-caption text-muted-foreground">管理岗位描述和招聘信息</p>
          </div>
        </div>
      </div>
    </div>
    <div v-if="jdData.length === 0 && !isDataLoading" class="rounded-xl border border-dashed border-border bg-card p-6 text-center">
      <Briefcase class="mx-auto mb-2 size-8 text-muted-foreground/50" />
      <p class="text-sm text-muted-foreground">暂无 JD 数据</p>
      <router-link to="/import" class="mt-2 inline-block text-sm text-primary hover:underline">去导入 JD</router-link>
    </div>
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
          <AppTooltip v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" text="打开链接">
            <a :href="safeUrl(row['来源链接'])" target="_blank" rel="noopener noreferrer" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 transition-colors duration-200">
              <ExternalLink class="size-4" />
              <span class="text-[10px] leading-tight">链接</span>
            </a>
          </AppTooltip>
          <AppTooltip v-if="displayUser?.is_admin || row.owner_id === displayUser?.id" text="删除">
            <button @click="deleteDataRow('jd', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1 transition-colors duration-200">
              <Trash2 class="size-4" />
              <span class="text-[10px] leading-tight">删除</span>
            </button>
          </AppTooltip>
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
import { Briefcase, ExternalLink, Trash2 } from '@lucide/vue'
import DataTable from '@/components/common/DataTable.vue'
import InlineEdit from '@/components/common/InlineEdit.vue'
import AppTooltip from '@/components/common/AppTooltip.vue'

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

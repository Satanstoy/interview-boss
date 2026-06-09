<template>
  <div class="w-full">
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="rows.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    />

    <Table class="rounded-xl border border-border bg-card shadow-sm">
      <TableHeader>
        <TableRow class="bg-card text-ink-500 dark:text-ink-400 text-xs border-border">
          <TableHead class="h-10 px-3 text-center w-10">选择</TableHead>
          <TableHead v-for="col in columns" :key="col.key" class="h-10 px-3" :class="col.class || ''" :style="col.width ? { width: col.width } : {}">
            {{ col.label }}
          </TableHead>
          <TableHead class="h-10 px-3 text-center w-[100px]">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody v-auto-animate>
        <TableRow v-for="(row, idx) in paginatedRows" :key="row.id"
          :data-row-id="row.id"
          class="text-sm animate-fade-in"
          :class="[
            highlightId != null && highlightId == row.id ? 'highlight-row' : '',
            isSelected(row.id) ? 'bg-surface-100/80 dark:bg-ink-800/70' : 'bg-white dark:bg-surface-900'
          ]"
          :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
        >
          <TableCell class="px-3 py-2.5 text-center">
            <input type="checkbox" :checked="isSelected(row.id)" @change="$emit('toggle-item', row.id)"
              class="size-4 text-primary-600 rounded-md border-surface-300 dark:border-ink-600 focus:ring-primary-500 cursor-pointer transition">
          </TableCell>
          <TableCell v-for="col in columns" :key="col.key" class="px-3 py-2.5 break-words text-ink-700 dark:text-ink-200" :class="col.cellClass || ''" :style="col.width ? { width: col.width } : {}">
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
              {{ row[col.frontendKey || col.key] }}
            </slot>
          </TableCell>
          <TableCell class="px-3 py-2.5 text-center">
            <slot name="actions" :row="row" />
          </TableCell>
        </TableRow>
        <TableRow v-if="rows.length === 0">
          <TableCell :colspan="columns.length + 2" class="p-16 text-center">
            <div class="flex flex-col items-center">
              <div class="size-16 rounded-2xl bg-surface-100 dark:bg-ink-800 flex items-center justify-center mb-4">
                <Inbox class="size-8 text-ink-300 dark:text-ink-600" />
              </div>
              <p class="text-ink-500 dark:text-ink-400 font-medium mb-1">暂无数据</p>
              <p class="text-sm text-ink-400 dark:text-ink-500">试试切换筛选条件或录入更多内容</p>
            </div>
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>

    <PaginationBar
      :current-page="currentPage"
      :page-size="pageSize"
      :total="rows.length"
      @update:current-page="$emit('update:currentPage', $event)"
      @update:page-size="$emit('update:pageSize', $event)"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Inbox } from '@lucide/vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import BatchActionPanel from '@/components/common/BatchActionPanel.vue'
import PaginationBar from '@/components/common/PaginationBar.vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false },
  batchActions: { type: Array, default: () => [] },
  currentPage: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  highlightId: { type: Number, default: null }
})
defineEmits(['toggle-select-all', 'invert-selection', 'toggle-item', 'update:currentPage', 'update:pageSize'])

const paginatedRows = computed(() => {
  const start = (props.currentPage - 1) * props.pageSize
  return props.rows.slice(start, start + props.pageSize)
})
</script>

<style scoped>
.highlight-row {
  animation: highlight-pulse 4s ease-out forwards;
}
@keyframes highlight-pulse {
  0%, 30% { background-color: rgba(248, 221, 165, 0.5); }
  100% { background-color: transparent; }
}
:global(.dark) .highlight-row {
  animation: highlight-pulse-dark 4s ease-out forwards;
}
@keyframes highlight-pulse-dark {
  0%, 30% { background-color: rgba(248, 221, 165, 0.2); }
  100% { background-color: transparent; }
}
</style>

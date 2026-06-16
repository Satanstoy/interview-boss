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
        <TableRow class="bg-card text-muted-foreground text-xs border-border">
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
            isSelected(row.id) ? 'bg-muted/80 dark:bg-card/70' : 'bg-background'
          ]"
          :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
        >
          <TableCell class="px-3 py-2.5 text-center">
            <input type="checkbox" :checked="isSelected(row.id)" @change="$emit('toggle-item', row.id)"
              class="size-4 text-primary-600 rounded-md border-border focus:ring-primary-500 cursor-pointer transition">
          </TableCell>
          <TableCell v-for="col in columns" :key="col.key" class="px-3 py-2.5 break-words text-foreground" :class="col.cellClass || ''" :style="col.width ? { width: col.width } : {}">
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
              {{ row[col.frontendKey || col.key] }}
            </slot>
          </TableCell>
          <TableCell class="px-3 py-2.5 text-center">
            <slot name="actions" :row="row" />
          </TableCell>
        </TableRow>
        <TableRow v-if="rows.length === 0">
          <TableCell :colspan="columns.length + 2" class="p-0">
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Inbox />
                </EmptyMedia>
                <EmptyTitle>暂无数据</EmptyTitle>
                <EmptyDescription>试试切换筛选条件或录入更多内容</EmptyDescription>
              </EmptyHeader>
            </Empty>
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>

    <Pagination
      v-if="totalPages > 1"
      as="div"
      class="flex items-center justify-between gap-3 mt-4 px-1 w-full"
      :items-per-page="pageSize"
      :total="rows.length"
      :page="currentPage"
      @update:page="(p) => emit('update:currentPage', p)"
    >
      <div class="text-xs text-muted-foreground tabular-nums">
        共 {{ rows.length }} 条，第 {{ currentPage }}/{{ totalPages }} 页
      </div>
      <PaginationContent v-slot="{ items }">
        <PaginationPrevious />
        <template v-for="(item, idx) in items" :key="idx">
          <PaginationItem
            v-if="item.type === 'page'"
            :value="item.value"
            :is-active="item.value === currentPage"
          >
            {{ item.value }}
          </PaginationItem>
          <PaginationEllipsis v-else-if="item.type === 'ellipsis'" />
        </template>
        <PaginationNext />
      </PaginationContent>
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <span>每页</span>
        <Select :model-value="String(pageSize)" @update:model-value="(v) => { emit('update:pageSize', Number(v)); emit('update:currentPage', 1) }">
          <SelectTrigger class="h-8 text-xs min-w-[60px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="s in pageSizeOptions" :key="s" :value="String(s)">{{ s }}</SelectItem>
          </SelectContent>
        </Select>
        <span>条</span>
      </div>
    </Pagination>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Inbox } from '@lucide/vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Pagination, PaginationContent, PaginationEllipsis, PaginationItem, PaginationNext, PaginationPrevious } from '@/components/ui/pagination'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import BatchActionPanel from '@/components/common/BatchActionPanel.vue'

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
const emit = defineEmits(['toggle-select-all', 'invert-selection', 'toggle-item', 'update:currentPage', 'update:pageSize'])

const pageSizeOptions = [10, 20, 50, 100]

const totalPages = computed(() => Math.max(1, Math.ceil(props.rows.length / props.pageSize)))

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

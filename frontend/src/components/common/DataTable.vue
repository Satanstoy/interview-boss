<template>
  <div class="w-full min-w-0">
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="rows.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    />

    <div v-if="isDesktop" class="w-full min-w-0 overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <Table class="min-w-full table-fixed">
        <TableHeader>
          <TableRow class="bg-muted/40 text-muted-foreground text-xs border-border hover:bg-muted/40">
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
            <TableCell class="px-3 py-2.5 text-center whitespace-nowrap">
              <input type="checkbox" :checked="isSelected(row.id)" @change="$emit('toggle-item', row.id)"
                class="size-4 text-primary-600 rounded-md border-border focus:ring-primary-500 cursor-pointer transition">
            </TableCell>
            <TableCell v-for="col in columns" :key="col.key" class="px-3 py-2.5 whitespace-normal break-words text-foreground" :class="col.cellClass || ''" :style="col.width ? { width: col.width } : {}">
              <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
                {{ row[col.frontendKey || col.key] }}
              </slot>
            </TableCell>
            <TableCell class="px-3 py-2.5 text-center whitespace-nowrap">
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
    </div>

    <div v-else class="space-y-3">
      <article
        v-for="(row, idx) in paginatedRows"
        :key="row.id"
        :data-row-id="row.id"
        data-mobile-row-card
        class="animate-fade-in rounded-xl border border-border bg-card p-3 shadow-sm"
        :class="[
          highlightId != null && highlightId == row.id ? 'highlight-row' : '',
          isSelected(row.id) ? 'bg-muted/80 dark:bg-card/70' : ''
        ]"
        :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
      >
        <div class="flex items-start gap-3 border-b border-border/70 pb-3">
          <input
            type="checkbox"
            :checked="isSelected(row.id)"
            class="mt-0.5 size-4 shrink-0 cursor-pointer rounded-md border-border text-primary-600 transition focus:ring-primary-500"
            @change="$emit('toggle-item', row.id)"
          >
          <div v-if="primaryColumn" class="min-w-0 flex-1">
            <div class="text-[11px] font-medium text-muted-foreground">{{ primaryColumn.label }}</div>
            <div class="mt-0.5 min-w-0 break-words text-sm font-semibold text-foreground">
              <slot :name="`cell-${primaryColumn.key}`" :row="row" :value="row[primaryColumn.frontendKey || primaryColumn.key]">
                {{ row[primaryColumn.frontendKey || primaryColumn.key] }}
              </slot>
            </div>
          </div>
          <div class="shrink-0">
            <slot name="actions" :row="row" />
          </div>
        </div>

        <dl class="mt-3 grid gap-3">
          <div
            v-for="col in secondaryColumns"
            :key="col.key"
            class="min-w-0"
          >
            <dt class="text-[11px] font-medium text-muted-foreground">{{ col.label }}</dt>
            <dd class="mt-1 min-w-0 whitespace-pre-wrap break-words text-sm text-foreground" :class="col.cellClass || ''">
              <slot :name="`cell-${col.key}`" :row="row" :value="row[col.frontendKey || col.key]">
                {{ row[col.frontendKey || col.key] }}
              </slot>
            </dd>
          </div>
        </dl>
      </article>

      <div v-if="rows.length === 0" class="rounded-xl border border-border bg-card shadow-sm">
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Inbox />
            </EmptyMedia>
            <EmptyTitle>暂无数据</EmptyTitle>
            <EmptyDescription>试试切换筛选条件或录入更多内容</EmptyDescription>
          </EmptyHeader>
        </Empty>
      </div>
    </div>

    <Pagination
      v-if="totalPages > 1"
      as="div"
      class="mt-4 flex w-full flex-col items-stretch gap-3 px-1 sm:flex-row sm:items-center sm:justify-between"
      :items-per-page="pageSize"
      :total="rows.length"
      :page="currentPage"
      @update:page="(p) => emit('update:currentPage', p)"
    >
      <div class="text-xs text-muted-foreground tabular-nums">
        共 {{ rows.length }} 条，第 {{ currentPage }}/{{ totalPages }} 页
      </div>
      <PaginationContent v-slot="{ items }" class="justify-center">
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
import { computed, onMounted, onUnmounted, ref } from 'vue'
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
const isDesktop = ref(true)
let desktopMediaQuery = null
let removeDesktopMediaListener = () => {}

const totalPages = computed(() => Math.max(1, Math.ceil(props.rows.length / props.pageSize)))

const primaryColumn = computed(() => props.columns[0] || null)

const secondaryColumns = computed(() => props.columns.slice(1))

const paginatedRows = computed(() => {
  const start = (props.currentPage - 1) * props.pageSize
  return props.rows.slice(start, start + props.pageSize)
})

onMounted(() => {
  desktopMediaQuery = window.matchMedia('(min-width: 768px)')
  const syncDesktop = () => { isDesktop.value = desktopMediaQuery.matches }
  syncDesktop()

  if (desktopMediaQuery.addEventListener) {
    desktopMediaQuery.addEventListener('change', syncDesktop)
    removeDesktopMediaListener = () => desktopMediaQuery.removeEventListener('change', syncDesktop)
  } else {
    desktopMediaQuery.addListener(syncDesktop)
    removeDesktopMediaListener = () => desktopMediaQuery.removeListener(syncDesktop)
  }
})

onUnmounted(() => {
  removeDesktopMediaListener()
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

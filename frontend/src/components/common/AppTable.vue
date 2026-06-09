<template>
  <div class="w-full rounded-xl border border-border bg-card shadow-sm overflow-hidden">
    <Table>
      <!-- Loading overlay -->
      <div
        v-if="loading"
        class="absolute inset-0 z-10 flex items-center justify-center bg-card/80 backdrop-blur-sm"
      >
        <div class="flex items-center gap-2.5">
          <Loader2 class="h-5 w-5 animate-spin text-primary" />
          <span class="text-sm font-medium text-ink-600 dark:text-ink-300">加载中...</span>
        </div>
      </div>

      <TableHeader>
        <TableRow class="bg-surface-50/50 dark:bg-ink-800/50 hover:bg-surface-50/50 dark:hover:bg-ink-800/50">
          <TableHead
            v-for="col in columns"
            :key="col.key"
            class="px-4 text-ink-500 dark:text-ink-400"
            :class="col.headerClass || ''"
            :style="col.width ? { width: col.width } : {}"
          >
            {{ col.label }}
          </TableHead>
        </TableRow>
      </TableHeader>

      <TableBody>
        <template v-if="rows.length > 0">
          <TableRow
            v-for="(row, idx) in rows"
            :key="rowKey ? row[rowKey] : idx"
            class="animate-fade-in"
            :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
          >
            <TableCell
              v-for="col in columns"
              :key="col.key"
              class="p-4 text-ink-700 dark:text-ink-200"
              :class="col.cellClass || ''"
              :style="col.width ? { width: col.width } : {}"
            >
              <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
                {{ row[col.frontendKey || col.key] }}
              </slot>
            </TableCell>
          </TableRow>
        </template>

        <TableEmpty v-else-if="!loading" :colspan="columns.length">
          <div class="flex flex-col items-center justify-center text-center">
            <div class="size-14 mb-4 rounded-2xl bg-surface-100 dark:bg-ink-800 flex items-center justify-center">
              <Inbox class="size-7 text-ink-300 dark:text-ink-600" />
            </div>
            <p class="text-sm font-medium text-ink-600 dark:text-ink-400 mb-1">{{ emptyText }}</p>
            <p v-if="emptyDescription" class="text-xs text-ink-400 dark:text-ink-500">{{ emptyDescription }}</p>
          </div>
        </TableEmpty>
      </TableBody>
    </Table>
  </div>
</template>

<script setup>
import { Loader2, Inbox } from '@lucide/vue'
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
  emptyDescription: { type: String, default: '' },
  rowKey: { type: String, default: 'id' },
})
</script>

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
          <span class="text-sm font-medium text-muted-foreground">加载中...</span>
        </div>
      </div>

      <TableHeader>
        <TableRow class="bg-muted/50 hover:bg-muted/50">
          <TableHead
            v-for="col in columns"
            :key="col.key"
            class="px-4 text-muted-foreground"
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
              class="p-4 text-foreground"
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
            <div class="size-14 mb-4 rounded-xl bg-muted flex items-center justify-center">
              <Inbox class="size-7 text-muted-foreground/50" />
            </div>
            <p class="text-sm font-medium text-muted-foreground mb-1">{{ emptyText }}</p>
            <p v-if="emptyDescription" class="text-xs text-muted-foreground/80">{{ emptyDescription }}</p>
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

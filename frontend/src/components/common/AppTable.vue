<template>
  <div class="w-full rounded-xl border border-border bg-card shadow-sm overflow-hidden">
    <!-- Loading overlay -->
    <div v-if="loading" class="relative">
      <div class="absolute inset-0 z-10 flex items-center justify-center bg-card/80 backdrop-blur-sm">
        <div class="flex items-center gap-2.5">
          <svg class="animate-spin h-5 w-5 text-primary" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <span class="text-sm font-medium text-ink-600 dark:text-ink-300">加载中...</span>
        </div>
      </div>
    </div>

    <div class="w-full overflow-x-auto custom-scrollbar">
      <table class="w-full caption-bottom text-sm">
        <thead>
          <tr class="border-b border-border bg-surface-50/50 dark:bg-ink-800/50">
            <th
              v-for="col in columns"
              :key="col.key"
              class="h-10 px-4 text-left align-middle font-medium text-ink-500 dark:text-ink-400 whitespace-nowrap"
              :class="col.headerClass || ''"
              :style="col.width ? { width: col.width } : {}"
            >
              {{ col.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-if="rows.length > 0">
            <tr
              v-for="(row, idx) in rows"
              :key="rowKey ? row[rowKey] : idx"
              class="border-b border-border/50 transition-colors hover:bg-surface-50/70 dark:hover:bg-ink-800/40 animate-fade-in"
              :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
            >
              <td
                v-for="col in columns"
                :key="col.key"
                class="p-4 align-middle text-ink-700 dark:text-ink-200"
                :class="col.cellClass || ''"
                :style="col.width ? { width: col.width } : {}"
              >
                <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
                  {{ row[col.frontendKey || col.key] }}
                </slot>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && rows.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
      <div class="w-14 h-14 mb-4 rounded-2xl bg-surface-100 dark:bg-ink-800 flex items-center justify-center">
        <svg class="w-7 h-7 text-ink-300 dark:text-ink-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      </div>
      <p class="text-sm font-medium text-ink-600 dark:text-ink-400 mb-1">{{ emptyText }}</p>
      <p v-if="emptyDescription" class="text-xs text-ink-400 dark:text-ink-500">{{ emptyDescription }}</p>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
  emptyDescription: { type: String, default: '' },
  rowKey: { type: String, default: 'id' },
})
</script>

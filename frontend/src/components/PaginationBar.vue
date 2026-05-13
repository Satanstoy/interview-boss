<template>
  <div v-if="totalPages > 1" class="flex items-center justify-between gap-3 mt-4 px-1">
    <!-- Left: info -->
    <div class="text-xs text-ink-400 dark:text-ink-500 tabular-nums">
      共 {{ total }} 条，第 {{ currentPage }}/{{ totalPages }} 页
    </div>

    <!-- Center: page buttons -->
    <div class="flex items-center gap-1">
      <button
        :disabled="currentPage <= 1"
        @click="go(currentPage - 1)"
        class="page-btn"
        :class="currentPage <= 1 ? 'opacity-40 cursor-not-allowed' : 'hover:bg-surface-100 dark:hover:bg-ink-700'"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/></svg>
      </button>

      <template v-for="p in visiblePages" :key="p">
        <span v-if="p === '...'" class="px-1 text-ink-300 dark:text-ink-600 text-sm select-none">...</span>
        <button
          v-else
          @click="go(p)"
          class="page-btn min-w-[32px] text-xs font-medium tabular-nums"
          :class="p === currentPage
            ? 'bg-primary-500 text-white shadow-sm'
            : 'text-ink-600 dark:text-ink-400 hover:bg-surface-100 dark:hover:bg-ink-700'"
        >
          {{ p }}
        </button>
      </template>

      <button
        :disabled="currentPage >= totalPages"
        @click="go(currentPage + 1)"
        class="page-btn"
        :class="currentPage >= totalPages ? 'opacity-40 cursor-not-allowed' : 'hover:bg-surface-100 dark:hover:bg-ink-700'"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/></svg>
      </button>
    </div>

    <!-- Right: page size selector -->
    <div class="flex items-center gap-2 text-xs text-ink-400 dark:text-ink-500">
      <span>每页</span>
      <RoundedSelect
        :model-value="pageSize"
        @update:model-value="$emit('update:pageSize', $event); $emit('update:currentPage', 1)"
        :options="pageSizeOptions.map(s => ({ value: s, label: String(s) }))"
        size="sm"
        trigger-class="min-w-[60px]"
      />
      <span>条</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import RoundedSelect from './RoundedSelect.vue'

const props = defineProps({
  currentPage: { type: Number, required: true },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, required: true },
  pageSizeOptions: { type: Array, default: () => [10, 20, 50, 100] }
})

const emit = defineEmits(['update:currentPage', 'update:pageSize'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const visiblePages = computed(() => {
  const pages = []
  const cur = props.currentPage
  const last = totalPages.value

  if (last <= 7) {
    for (let i = 1; i <= last; i++) pages.push(i)
    return pages
  }

  pages.push(1)
  if (cur > 3) pages.push('...')

  const start = Math.max(2, cur - 1)
  const end = Math.min(last - 1, cur + 1)
  for (let i = start; i <= end; i++) pages.push(i)

  if (cur < last - 2) pages.push('...')
  pages.push(last)

  return pages
})

const go = (page) => {
  if (page < 1 || page > totalPages.value) return
  emit('update:currentPage', page)
}
</script>

<style scoped>
.page-btn {
  @apply flex items-center justify-center w-8 h-8 rounded-lg transition-all duration-150 select-none;
}
</style>

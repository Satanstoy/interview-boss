<template>
  <div v-if="totalPages > 1" class="flex items-center justify-between gap-3 mt-4 px-1">
    <!-- Left: info -->
    <div class="text-xs text-ink-400 dark:text-ink-500 tabular-nums">
      共 {{ total }} 条，第 {{ currentPage }}/{{ totalPages }} 页
    </div>

    <!-- Center: page buttons -->
    <div class="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon-sm"
        :disabled="currentPage <= 1"
        @click="go(currentPage - 1)"
      >
        <ChevronLeft class="w-4 h-4" />
      </Button>

      <template v-for="p in visiblePages" :key="p">
        <span v-if="p === '...'" class="px-1 text-ink-300 dark:text-ink-600 text-sm select-none">...</span>
        <Button
          v-else
          :variant="p === currentPage ? 'default' : 'outline'"
          size="sm"
          class="min-w-[32px] tabular-nums"
          @click="go(p)"
        >
          {{ p }}
        </Button>
      </template>

      <Button
        variant="outline"
        size="icon-sm"
        :disabled="currentPage >= totalPages"
        @click="go(currentPage + 1)"
      >
        <ChevronRight class="w-4 h-4" />
      </Button>
    </div>

    <!-- Right: page size selector -->
    <div class="flex items-center gap-2 text-xs text-ink-400 dark:text-ink-500">
      <span>每页</span>
      <Select :model-value="String(pageSize)" @update:model-value="$emit('update:pageSize', Number($event)); $emit('update:currentPage', 1)">
        <SelectTrigger class="h-8 text-xs min-w-[60px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="s in pageSizeOptions" :key="s" :value="String(s)">{{ s }}</SelectItem>
        </SelectContent>
      </Select>
      <span>条</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

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


<template>
  <div class="rounded-xl border border-border bg-card shadow-sm p-3 mb-3">
    <div class="flex flex-wrap gap-3 items-center">
      <!-- Search input using AppSearchForm pattern -->
      <div class="flex-1 min-w-[200px] relative">
        <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <svg class="h-4 w-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <input
          v-model="localQuery"
          type="text"
          class="w-full h-9 pl-9 pr-9 rounded-md border border-input bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:border-ring transition-colors"
          placeholder="搜索题目关键词..."
        />
        <button
          v-if="localQuery"
          @click="localQuery = ''"
          class="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
          aria-label="清除搜索"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Difficulty filter -->
      <Select :model-value="filterDifficulty" @update:model-value="$emit('update:filterDifficulty', $event)">
        <SelectTrigger class="min-w-[120px] h-9 text-sm">
          <SelectValue placeholder="全部难度" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="">全部难度</SelectItem>
          <SelectItem value="L1">L1 - 基础</SelectItem>
          <SelectItem value="L2">L2 - 中等</SelectItem>
          <SelectItem value="L3">L3 - 困难</SelectItem>
        </SelectContent>
      </Select>

      <!-- Filter chips slot -->
      <div v-if="$slots.filters" class="flex items-center gap-2 flex-wrap">
        <slot name="filters" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'


const props = defineProps({
  searchQuery: { type: String, default: '' },
  filterDifficulty: { type: String, default: '' },
})

const emit = defineEmits(['update:searchQuery', 'update:filterDifficulty'])

const localQuery = ref(props.searchQuery)
let debounceTimer = null

watch(localQuery, (val) => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => emit('update:searchQuery', val), 300)
})

watch(() => props.searchQuery, (val) => {
  if (val !== localQuery.value) localQuery.value = val
})
</script>

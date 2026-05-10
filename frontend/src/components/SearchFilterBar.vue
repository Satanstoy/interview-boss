<template>
  <div class="mb-4 flex flex-wrap gap-3 items-center">
    <div class="flex-1 min-w-[200px] relative">
      <svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-400 dark:text-ink-500 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
      </svg>
      <input
        v-model="localQuery"
        type="text"
        class="w-full border border-surface-200 dark:border-ink-600 rounded-xl pl-10 pr-10 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-200 placeholder-ink-400 dark:placeholder-ink-500 shadow-card focus:shadow-card-hover focus:border-primary-300 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-100 dark:focus:ring-primary-900 transition-all duration-200"
        placeholder="搜索题目关键词..."
      />
      <button
        v-if="localQuery"
        @click="localQuery = ''"
        class="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-700 transition-colors duration-200"
        aria-label="清除搜索"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>
    <select
      :value="filterDifficulty"
      @change="$emit('update:filterDifficulty', $event.target.value)"
      class="border border-surface-200 dark:border-ink-600 rounded-xl px-4 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-200 shadow-card focus:border-primary-300 dark:focus:border-primary-500 focus:ring-2 focus:ring-primary-100 dark:focus:ring-primary-900 transition-all duration-200"
    >
      <option value="">全部难度</option>
      <option value="L1">L1 - 基础</option>
      <option value="L2">L2 - 中等</option>
      <option value="L3">L3 - 困难</option>
    </select>
    <button
      v-if="showStarredToggle"
      @click="$emit('update:showStarredOnly', !showStarredOnly)"
      class="px-4 py-2.5 text-sm rounded-xl border transition-all duration-200 flex items-center gap-1.5"
      :class="showStarredOnly
        ? 'bg-amber-50 dark:bg-amber-900/30 border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-400 shadow-sm'
        : 'bg-white dark:bg-surface-800 border-surface-200 dark:border-ink-600 text-ink-500 dark:text-ink-400 hover:bg-surface-50 dark:hover:bg-surface-700 shadow-card'"
    >
      <svg class="w-4 h-4" :fill="showStarredOnly ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
      </svg>
      {{ showStarredOnly ? '仅看收藏' : '全部' }}
    </button>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  searchQuery: { type: String, default: '' },
  filterDifficulty: { type: String, default: '' },
  showStarredOnly: { type: Boolean, default: false },
  showStarredToggle: { type: Boolean, default: true }
})

const emit = defineEmits(['update:searchQuery', 'update:filterDifficulty', 'update:showStarredOnly'])

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

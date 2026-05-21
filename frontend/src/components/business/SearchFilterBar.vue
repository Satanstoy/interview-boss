<template>
  <div class="flex flex-wrap gap-3 items-center">
    <div class="flex-1 min-w-[200px] relative">
      <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-400 dark:text-ink-500 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
      </svg>
      <input
        v-model="localQuery"
        type="text"
        class="w-full border border-surface-200 dark:border-ink-700 rounded-xl pl-9 pr-9 py-2 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-200 placeholder-ink-400 dark:placeholder-ink-500 focus:border-primary-300 dark:focus:border-primary-600 focus:ring-2 focus:ring-primary-100 dark:focus:ring-primary-900/50 transition-all duration-200 outline-none"
        placeholder="搜索题目关键词..."
      />
      <button
        v-if="localQuery"
        @click="localQuery = ''"
        class="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 rounded-full text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-700 transition-colors duration-200"
        aria-label="清除搜索"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>
    <RoundedSelect
      :model-value="filterDifficulty"
      @update:model-value="$emit('update:filterDifficulty', $event)"
      :options="difficultyOptions"
      placeholder="全部难度"
      size="md"
      trigger-class="min-w-[120px]"
    />
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import RoundedSelect from '@/components/common/RoundedSelect.vue'

const difficultyOptions = [
  { value: '', label: '全部难度' },
  { value: 'L1', label: 'L1 - 基础' },
  { value: 'L2', label: 'L2 - 中等' },
  { value: 'L3', label: 'L3 - 困难' },
]

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

<template>
  <div class="mb-4 flex flex-wrap gap-3 items-center">
    <div class="flex-1 min-w-[200px]">
      <input
        v-model="localQuery"
        type="text"
        class="w-full border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-blue-500 focus:border-blue-500"
        placeholder="搜索题目关键词..."
      />
    </div>
    <select
      :value="filterDifficulty"
      @change="$emit('update:filterDifficulty', $event.target.value)"
      class="border border-gray-300 rounded-lg px-4 py-2 text-sm focus:ring-blue-500 focus:border-blue-500"
    >
      <option value="">全部难度</option>
      <option value="L1">L1-基础</option>
      <option value="L2">L2-中等</option>
      <option value="L3">L3-困难</option>
    </select>
    <button
      v-if="showStarredToggle"
      @click="$emit('update:showStarredOnly', !showStarredOnly)"
      class="px-3 py-2 text-sm rounded-lg border transition"
      :class="showStarredOnly ? 'bg-yellow-100 border-yellow-300 text-yellow-700' : 'bg-white border-gray-300 text-gray-500 hover:bg-gray-50'"
    >
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

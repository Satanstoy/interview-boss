<template>
  <div class="flex flex-wrap border-b bg-gray-50">
    <button
      v-for="tab in tabs" :key="tab.key"
      @click="$emit('update:activeTab', tab.key)"
      class="flex-1 min-w-0 py-3 lg:py-4 text-sm lg:text-base font-semibold transition-colors"
      :class="activeTab === tab.key ? tab.activeClass + ' bg-white border-b-2' : 'text-gray-400 hover:text-gray-600'"
    >
      {{ tab.label }}
    </button>
  </div>
</template>

<script setup>
defineProps({ activeTab: { type: String, default: 'MasterBank' } })
defineEmits(['update:activeTab'])

const tabs = [
  { key: 'JD', label: 'JD 筛选', activeClass: 'text-blue-600 border-blue-600' },
  { key: 'Interview', label: '面经库', activeClass: 'text-gray-700 border-gray-500' },
  { key: 'MasterBank', label: '高频题库', activeClass: 'text-red-600 border-red-600' },
  { key: 'MockInterview', label: '题目抽测', activeClass: 'text-orange-600 border-orange-600' },
  { key: 'KnowledgeGraph', label: '知识图谱', activeClass: 'text-violet-600 border-violet-600' },
  { key: 'Import', label: '导入', activeClass: 'text-emerald-600 border-emerald-600' }
]
</script>

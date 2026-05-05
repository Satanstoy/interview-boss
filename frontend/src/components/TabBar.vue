<template>
  <div class="flex flex-wrap border-b border-gray-100 dark:border-gray-700 bg-gradient-to-b from-gray-50/80 to-white dark:from-surface-800 dark:to-surface-800 px-1">
    <button
      v-for="tab in tabs" :key="tab.key"
      @click="$emit('update:activeTab', tab.key)"
      class="relative flex-1 min-w-0 py-3 lg:py-3.5 text-sm font-semibold transition-all duration-200 rounded-t-lg mx-0.5"
      :class="activeTab === tab.key
        ? 'text-primary-600 dark:text-primary-400 bg-white dark:bg-surface-700 shadow-sm border border-gray-100 dark:border-gray-700 border-b-white dark:border-b-surface-800 -mb-px'
        : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-50/60 dark:hover:bg-gray-800/60'"
    >
      <span class="flex items-center justify-center gap-1.5">
        {{ tab.label }}
      </span>
      <div
        v-if="activeTab === tab.key"
        class="absolute bottom-0 left-1/2 -translate-x-1/2 w-8 h-0.5 bg-gradient-brand rounded-full"
      ></div>
    </button>
  </div>
</template>

<script setup>
defineProps({ activeTab: { type: String, default: 'MasterBank' } })
defineEmits(['update:activeTab'])

const tabs = [
  { key: 'JD', label: 'JD 筛选' },
  { key: 'Interview', label: '面经库' },
  { key: 'MasterBank', label: '高频题库' },
  { key: 'MockInterview', label: '题目抽测' },
  { key: 'KnowledgeGraph', label: '知识图谱' },
  { key: 'Import', label: '导入' }
]
</script>

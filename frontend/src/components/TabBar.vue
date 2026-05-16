<template>
  <div class="flex border-b border-surface-200/80 dark:border-ink-700/50 bg-white/60 dark:bg-surface-800/40">
    <button
      v-for="tab in tabs" :key="tab.key"
      @click="$emit('update:activeTab', tab.key)"
      class="relative px-5 py-3 text-sm font-semibold transition-colors duration-150"
      :class="[
        activeTab === tab.key
          ? 'text-primary-700 dark:text-primary-400'
          : 'text-ink-400 hover:text-ink-600 dark:hover:text-ink-300',
      ]"
    >
      <span class="flex items-center justify-center gap-1.5">
        {{ tab.label }}
      </span>
      <div
        v-if="activeTab === tab.key"
        class="absolute bottom-0 left-2 right-2 h-0.5 bg-primary-500 dark:bg-primary-400 rounded-full"
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

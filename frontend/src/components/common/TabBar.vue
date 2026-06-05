<template>
  <div class="relative">
    <div class="flex border-b border-surface-200/80 dark:border-ink-700/50 bg-white/60 dark:bg-surface-800/40 overflow-x-auto mobile-scroll-x" role="tablist" aria-label="页面导航">
      <button
        v-for="tab in tabs" :key="tab.key"
        @click="handleTabClick(tab.key)"
        :disabled="isTransitioning"
        class="relative px-4 h-10 text-sm font-semibold transition-all duration-200 flex-shrink-0 rounded-t-lg flex items-center justify-center disabled:opacity-60 disabled:cursor-not-allowed"
        :class="[
          activeTab === tab.key
            ? 'text-primary-700 dark:text-primary-400 bg-primary-50/60 dark:bg-primary-900/20'
            : 'text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-50/60 dark:hover:bg-surface-700/30',
        ]"
        role="tab"
        :aria-selected="activeTab === tab.key"
        :aria-controls="`tabpanel-${tab.key}`"
      >
        <span class="whitespace-nowrap">
          {{ tab.label }}
        </span>
        <Transition name="tab-indicator">
          <div
            v-if="activeTab === tab.key"
            class="absolute bottom-0 left-2 right-2 h-0.5 bg-primary-500 dark:bg-primary-400 rounded-full"
          ></div>
        </Transition>
      </button>
    </div>
    <!-- Scroll hint gradient (right edge, mobile only) -->
    <div class="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white/80 dark:from-surface-800/80 to-transparent pointer-events-none sm:hidden"></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ activeTab: { type: String, default: 'MasterBank' } })
const emit = defineEmits(['update:activeTab'])

const isTransitioning = ref(false)
let transitionTimer = null

function handleTabClick(tabKey) {
  if (isTransitioning.value) return
  
  isTransitioning.value = true
  emit('update:activeTab', tabKey)
  
  // 300ms 防抖，防止快速点击导致 Transition 竞态
  if (transitionTimer) clearTimeout(transitionTimer)
  transitionTimer = setTimeout(() => {
    isTransitioning.value = false
    transitionTimer = null
  }, 300)
}

const tabs = [
  { key: 'JD', label: 'JD 筛选' },
  { key: 'Interview', label: '面经库' },
  { key: 'MasterBank', label: '高频题库' },
  { key: 'Chat', label: '模拟面试' },
  { key: 'MockInterview', label: '题目抽测' },
  { key: 'KnowledgeGraph', label: '知识图谱' },
  { key: 'Import', label: '导入' },
  { key: 'Coding', label: '手撕代码' }
]
</script>

<style scoped>
.tab-indicator-enter-active {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s ease;
}
.tab-indicator-leave-active {
  transition: opacity 0.15s ease;
}
.tab-indicator-enter-from {
  opacity: 0;
  transform: scaleX(0);
  transform-origin: left;
}
.tab-indicator-leave-to {
  opacity: 0;
}
</style>

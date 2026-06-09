<template>
  <div class="relative">
    <Tabs
      :model-value="activeTab"
      @update:model-value="handleTabClick"
      class="w-fit"
    >
      <TabsList class="bg-transparent border-b border-border/80/50 overflow-x-auto mobile-scroll-x w-full">
        <TabsTrigger
          v-for="tab in tabs"
          :key="tab.key"
          :value="tab.key"
          :disabled="isTransitioning"
          class="flex-shrink-0"
        >
          {{ tab.label }}
        </TabsTrigger>
      </TabsList>
    </Tabs>
    <!-- Scroll hint gradient (right edge, mobile only) -->
    <div class="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white/80 dark:from-surface-800/80 to-transparent pointer-events-none sm:hidden"></div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

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

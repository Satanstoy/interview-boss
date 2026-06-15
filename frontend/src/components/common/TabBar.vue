<template>
  <div class="relative">
    <Tabs
      :model-value="activeRoute"
      @update:model-value="handleTabClick"
      class="w-fit"
    >
      <TabsList class="bg-transparent border-b border-border/80/50 overflow-x-auto mobile-scroll-x w-full">
        <TabsTrigger
          v-for="tab in tabs"
          :key="tab.route"
          :value="tab.route"
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
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const router = useRouter()
const route = useRoute()
const activeRoute = computed(() => route.path)

const isTransitioning = ref(false)
let transitionTimer = null

function handleTabClick(tabRoute) {
  if (isTransitioning.value) return

  isTransitioning.value = true
  router.push(tabRoute)

  // 300ms 防抖，防止快速点击导致 Transition 竞态
  if (transitionTimer) clearTimeout(transitionTimer)
  transitionTimer = setTimeout(() => {
    isTransitioning.value = false
    transitionTimer = null
  }, 300)
}

const tabs = [
  { route: '/jd', label: 'JD 筛选' },
  { route: '/interview', label: '面经库' },
  { route: '/master-bank', label: '高频题库' },
  { route: '/chat', label: '模拟面试' },
  { route: '/mock-interview', label: '题目抽测' },
  { route: '/knowledge-graph', label: '知识图谱' },
  { route: '/import', label: '导入' },
  { route: '/coding', label: '手撕代码' }
]
</script>

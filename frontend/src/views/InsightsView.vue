<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import InsightsOverview from '@/components/business/InsightsOverview.vue'
import InsightsReadiness from '@/components/business/InsightsReadiness.vue'
import InsightsReviews from '@/components/business/InsightsReviews.vue'
import { useInsightsData } from '@/composables/useInsightsData.js'

const route = useRoute()
const { snapshot, isLoading, error, loadInsights } = useInsightsData()

const activeView = computed(() => {
  if (route.name === 'insights-readiness') return 'readiness'
  if (route.name === 'insights-reviews') return 'reviews'
  return 'overview'
})

onMounted(loadInsights)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div v-if="isLoading && !snapshot" class="flex h-full items-center justify-center">
      <AsyncLoading />
    </div>

    <div v-else-if="error && !snapshot" class="flex h-full items-center justify-center px-6">
      <div class="max-w-md rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
        <h1 class="text-lg font-semibold text-foreground">洞察暂时不可用</h1>
        <p class="mt-2 text-sm text-muted-foreground">请稍后重试，或先从题库和模拟面试开始积累数据。</p>
        <button class="mt-4 rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted" @click="loadInsights">重新加载</button>
      </div>
    </div>

    <InsightsOverview
      v-else-if="activeView === 'overview'"
      :snapshot="snapshot"
    />
    <InsightsReadiness
      v-else-if="activeView === 'readiness'"
      :snapshot="snapshot"
    />
    <InsightsReviews
      v-else
      :snapshot="snapshot"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Button } from '@/components/ui/button'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import InsightsOverview from '@/components/business/InsightsOverview.vue'
import InsightsReadiness from '@/components/business/InsightsReadiness.vue'
import InsightsReviews from '@/components/business/InsightsReviews.vue'
import { useInsightsData } from '@/composables/useInsightsData.js'

const route = useRoute()
const { snapshot, practiceActivity, isLoading, practiceLoading, error, loadInsights, loadPracticeActivity } = useInsightsData()
const reloading = ref(false)

const activeView = computed(() => {
  if (route.name === 'insights-readiness') return 'readiness'
  if (route.name === 'insights-reviews') return 'reviews'
  return 'overview'
})

onMounted(loadInsights)

watch(activeView, (view) => {
  if (view === 'overview' && practiceActivity.value === null) loadPracticeActivity()
}, { immediate: true })
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
        <Button class="mt-4" variant="outline" :disabled="reloading" @click="async () => { reloading = true; await loadInsights(); reloading = false }">
          {{ reloading ? '加载中...' : '重新加载' }}
        </Button>
      </div>
    </div>

    <template v-else-if="snapshot">
      <InsightsOverview
        v-if="activeView === 'overview'"
        :snapshot="snapshot"
        :practice-activity="practiceActivity"
        :practice-loading="practiceLoading"
      />
      <InsightsReadiness v-else-if="activeView === 'readiness'" :snapshot="snapshot" />
      <InsightsReviews v-else :snapshot="snapshot" />
    </template>

    <div v-else class="flex h-full items-center justify-center">
      <AsyncLoading />
    </div>
  </div>
</template>

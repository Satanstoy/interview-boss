<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <MockInterview ref="mockInterviewRef" :popular-tags="popularTags" />
  </div>
</template>

<script setup>
import { inject, ref, defineAsyncComponent } from 'vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const MockInterview = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/MockInterview.vue'),
})

const { popularTags } = inject('appData')
const mockInterviewRef = ref(null)
</script>

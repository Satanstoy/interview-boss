<template>
  <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
    <div class="mx-auto flex h-full min-h-0 max-w-[1600px] flex-col px-4 py-4 md:px-6 md:py-6">
      <CodingPractice class="min-h-0 flex-1" />
    </div>
  </div>
</template>

<script setup>
import { defineAsyncComponent } from 'vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const CodingPractice = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/CodingPractice.vue'),
})
</script>

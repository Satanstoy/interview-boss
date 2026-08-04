<template>
  <div class="px-4 py-4 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <CodingPractice />
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

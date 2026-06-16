<template>
  <div class="flex-1 min-h-0">
    <CodingPractice class="h-full" />
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

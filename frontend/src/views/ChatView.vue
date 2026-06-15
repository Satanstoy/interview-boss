<template>
  <div class="flex-1 min-h-0">
    <KeepAlive>
      <AsyncChatView :jd-list="jdData" :preview="isPreviewMode" class="flex-1 min-h-0" />
    </KeepAlive>
  </div>
</template>

<script setup>
import { inject, KeepAlive, defineAsyncComponent } from 'vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const AsyncChatView = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/ChatView.vue'),
})

const { jdData, isPreviewMode } = inject('appData')
</script>

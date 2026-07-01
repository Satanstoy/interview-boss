<!-- frontend/src/views/ChatView.vue -->
<template>
  <div class="flex-1 min-h-0">
    <KeepAlive>
      <AsyncChatView
        :jd-list="jdData"
        :interview-list="interviewData"
        :preview="isPreviewMode"
        :model-value="activeSessionId"
        @update:model-value="onSessionChange"
        class="flex-1 min-h-0"
      />
    </KeepAlive>
  </div>
</template>

<script setup>
import { inject, KeepAlive, defineAsyncComponent, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const { jdData, interviewData, isPreviewMode } = inject('appData')
const route = useRoute()
const router = useRouter()

const activeSessionId = ref(route.params.sessionId || null)

const AsyncChatView = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/ChatView.vue'),
})

// URL → 组件（用户通过 URL 直接访问某个对话）
watch(() => route.params.sessionId, (newId) => {
  if (newId) activeSessionId.value = newId
})

// 组件 → URL（用户在 UI 中选择对话）
function onSessionChange(id) {
  activeSessionId.value = id
  if (id) {
    router.replace(`/chat/${id}`)
  } else {
    router.replace('/chat')
  }
}
</script>

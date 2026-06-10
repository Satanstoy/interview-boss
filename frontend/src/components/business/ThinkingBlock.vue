<template>
  <div class="thinking-block">
    <button
      @click="isOpen = !isOpen"
      class="thinking-trigger"
      :class="{ streaming: isStreaming }"
    >
      <div class="flex items-center gap-2">
        <div class="thinking-icon">
          <svg v-if="isStreaming" class="animate-spin size-4" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg v-else class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        </div>
        <span class="text-sm font-medium">{{ displayLabel }}</span>
      </div>
      <svg
        class="size-4 transition-transform duration-200"
        :class="{ 'rotate-180': isOpen }"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <Transition name="expand">
      <div v-show="isOpen" class="thinking-content">
        <div class="thinking-text" ref="contentRef">{{ content }}</div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'

const props = defineProps({
  isStreaming: { type: Boolean, default: false },
  content: { type: String, default: '' },
  duration: { type: Number, default: 0 },
})

const isOpen = ref(true)
const contentRef = ref(null)

const displayLabel = computed(() => {
  if (props.isStreaming) return '正在思考中...'
  if (props.duration > 0) return `思考了 ${props.duration} 秒`
  return '思考过程'
})

// 流式时自动滚动到底部
watch(() => props.content, () => {
  if (contentRef.value && isOpen.value) {
    contentRef.value.scrollTop = contentRef.value.scrollHeight
  }
})

// 完成后自动折叠（延迟 500ms）
watch(() => props.isStreaming, (streaming) => {
  if (!streaming && props.content) {
    setTimeout(() => {
      isOpen.value = false
    }, 500)
  }
})

onMounted(() => {
  // 如果已经有内容且不在流式状态，默认折叠
  if (props.content && !props.isStreaming) {
    isOpen.value = false
  }
})
</script>

<style scoped>
.thinking-block {
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 12px;
  overflow: hidden;
  margin: 8px 0;
  background: var(--bg-secondary, #f9fafb);
}

.thinking-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 12px 16px;
  background: transparent;
  border: none;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
  transition: all 0.2s ease;
}

.thinking-trigger:hover {
  background: var(--bg-hover, #f3f4f6);
}

.thinking-trigger.streaming {
  color: var(--primary, #7c3aed);
}

.thinking-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
}

.thinking-content {
  padding: 0 16px 16px;
}

.thinking-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-tertiary, #9ca3af);
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 12px;
  background: var(--bg-primary, #ffffff);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e5e7eb);
}

.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 400px;
}

/* 暗色模式 */
:root.dark .thinking-block {
  border-color: #374151;
  background: #1f2937;
}

:root.dark .thinking-trigger {
  color: #9ca3af;
}

:root.dark .thinking-trigger:hover {
  background: #374151;
}

:root.dark .thinking-trigger.streaming {
  color: #a78bfa;
}

:root.dark .thinking-text {
  color: #d1d5db;
  background: #111827;
  border-color: #374151;
}
</style>

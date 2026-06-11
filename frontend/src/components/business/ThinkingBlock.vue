<template>
  <div class="mb-4">
    <!-- Trigger button -->
    <button
      @click="isOpen = !isOpen"
      class="flex items-center gap-2 text-xs text-muted-foreground/70 hover:text-muted-foreground transition-colors select-none"
    >
      <!-- Spinner while streaming -->
      <Loader2 v-if="isStreaming" :size="14" class="animate-spin" />
      <!-- Lightbulb when complete -->
      <Lightbulb v-else :size="14" />
      
      <span>{{ displayLabel }}</span>
      
      <!-- Pulsing ellipsis while streaming -->
      <span v-if="isStreaming && !isOpen" class="inline-flex gap-0.5">
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 0ms"></span>
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 200ms"></span>
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 400ms"></span>
      </span>
      
      <!-- Chevron -->
      <ChevronDown v-else :size="14" class="transition-transform duration-200" :class="{ 'rotate-180': isOpen }" />
    </button>

    <!-- Collapsible content -->
    <Transition name="expand">
      <div v-show="isOpen" class="mt-2">
        <div 
          ref="contentRef"
          class="text-xs leading-relaxed text-muted-foreground/70 max-h-[300px] overflow-y-auto whitespace-pre-wrap break-words p-3 rounded-lg bg-muted/30 border border-border/50"
        >{{ content }}</div>
        
        <!-- Pulsing ellipsis at bottom while streaming -->
        <div v-if="isStreaming" class="flex justify-center mt-2">
          <span class="inline-flex gap-0.5">
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 0ms"></span>
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 200ms"></span>
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 400ms"></span>
          </span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { Loader2, Lightbulb, ChevronDown } from '@lucide/vue'

const props = defineProps({
  isStreaming: { type: Boolean, default: false },
  content: { type: String, default: '' },
  duration: { type: Number, default: 0 },
})

const isOpen = ref(true)
const contentRef = ref(null)

const displayLabel = computed(() => {
  if (props.isStreaming) return '思考中'
  if (props.duration > 0) return `思考了 ${props.duration} 秒`
  return '思考过程'
})

watch(() => props.content, () => {
  if (contentRef.value && isOpen.value) {
    contentRef.value.scrollTop = contentRef.value.scrollHeight
  }
})

watch(() => props.isStreaming, (streaming) => {
  if (!streaming && props.content) {
    setTimeout(() => {
      isOpen.value = false
    }, 1000)
  }
})

onMounted(() => {
  if (props.content && !props.isStreaming) {
    isOpen.value = false
  }
})
</script>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 400px;
}
</style>

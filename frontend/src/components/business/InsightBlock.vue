<template>
  <div class="insight-block my-2">
    <button
      class="flex items-center gap-2 w-full text-left px-3 py-2 rounded-lg
             bg-amber-500/5 border border-amber-500/15 hover:bg-amber-500/10
             transition-colors duration-200"
      @click="isOpen = !isOpen"
    >
      <Lightbulb class="w-4 h-4 text-amber-500 shrink-0" />
      <span class="text-xs text-muted-foreground flex-1">
        面试官思考（{{ items.length }} 条）
      </span>
      <ChevronDown
        class="w-4 h-4 text-muted-foreground shrink-0 transition-transform duration-200"
        :class="{ 'rotate-180': isOpen }"
      />
    </button>
    <transition name="expand">
      <div v-show="isOpen" class="mt-1 space-y-1">
        <div
          v-for="(item, i) in items"
          :key="i"
          class="flex items-start gap-2 px-3 py-1.5 text-xs text-muted-foreground"
        >
          <span class="text-amber-500/70 mt-0.5">&#x1F4A1;</span>
          <span class="leading-relaxed">{{ item.text }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Lightbulb, ChevronDown } from '@lucide/vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  isStreaming: { type: Boolean, default: false },
})

const isOpen = ref(false)

onMounted(() => {
  // If streaming, start open; if loading historical, start collapsed
  isOpen.value = props.isStreaming
})
</script>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  max-height: 400px;
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}
</style>

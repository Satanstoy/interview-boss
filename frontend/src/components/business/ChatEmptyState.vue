<template>
  <div v-motion class="mx-auto flex max-w-2xl flex-1 flex-col items-center justify-center px-4 py-6 sm:px-6"
    :initial="{ opacity: 0, y: 16 }"
    :enter="{ opacity: 1, y: 0, transition: { duration: 400, easing: [0.25, 0.46, 0.45, 0.94] } }">
    <div class="mx-auto mb-4 flex size-16 items-center justify-center rounded-xl bg-primary/10 sm:mb-6 sm:size-20">
      <MessageSquare :size="40" class="text-primary" />
    </div>
    <h2 class="mb-2 text-center text-2xl font-bold text-foreground sm:mb-3 sm:text-3xl">开始模拟面试</h2>
    <div class="grid w-full max-w-lg grid-cols-1 gap-2.5 sm:grid-cols-2 sm:gap-4">
      <button v-for="suggestion in promptSuggestions" :key="suggestion.text"
        class="group flex min-h-16 items-start gap-3 rounded-xl border border-border bg-card p-3 text-left transition-all hover:border-border hover:bg-accent/50 sm:p-4"
        @click="emit('select', suggestion)">
        <div class="size-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 group-hover:bg-primary/20 transition-colors">
          <component :is="suggestion.icon" :size="20" class="text-primary" />
        </div>
        <div>
          <div class="text-sm font-semibold text-foreground">{{ suggestion.title }}</div>
          <div class="text-xs text-muted-foreground mt-1">{{ suggestion.description }}</div>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { MessageSquare } from '@lucide/vue'
import { promptSuggestions } from '@/constants/chatSuggestions.js'

const emit = defineEmits(['select'])
</script>

<template>
  <div class="flex flex-col sm:flex-row gap-3">
    <!-- Search input -->
    <div class="relative flex-1">
      <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
        <svg class="h-4 w-4 text-ink-400 dark:text-ink-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </div>
      <input
        :value="modelValue"
        type="text"
        :placeholder="placeholder"
        class="w-full h-9 pl-9 pr-9 rounded-md border border-input bg-transparent text-sm text-ink-800 dark:text-ink-200 placeholder:text-ink-400 dark:placeholder:text-ink-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:border-ring transition-colors"
        @input="$emit('update:modelValue', $event.target.value)"
        @keydown.enter="$emit('search')"
      />
      <button
        v-if="modelValue"
        type="button"
        class="absolute inset-y-0 right-0 pr-3 flex items-center text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 transition-colors"
        @click="$emit('update:modelValue', ''); $emit('reset')"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Filters slot -->
    <div v-if="$slots.filters" class="flex items-center gap-2 flex-wrap">
      <slot name="filters" />
    </div>

    <!-- Action buttons -->
    <div v-if="showButtons" class="flex items-center gap-2 shrink-0">
      <button
        type="button"
        class="inline-flex items-center justify-center gap-1.5 px-3 h-9 text-sm font-medium text-ink-700 dark:text-ink-300 bg-white dark:bg-surface-900 border border-surface-200 dark:border-ink-700 rounded-md transition-all hover:bg-surface-50 dark:hover:bg-ink-800 hover:border-surface-300 dark:hover:border-ink-600 active:scale-[0.98]"
        @click="$emit('reset')"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        重置
      </button>
      <button
        type="button"
        class="inline-flex items-center justify-center gap-1.5 px-4 h-9 text-sm font-medium text-primary-foreground bg-primary rounded-md transition-all hover:filter hover:brightness-95 active:scale-[0.98] shadow-sm"
        @click="$emit('search')"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        搜索
      </button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '搜索...' },
  showButtons: { type: Boolean, default: true },
})

defineEmits(['update:modelValue', 'search', 'reset'])
</script>

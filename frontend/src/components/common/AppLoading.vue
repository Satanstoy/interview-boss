<template>
  <!-- Spinner type -->
  <div v-if="type === 'spinner'" class="flex items-center justify-center" :class="wrapperClass">
    <div class="flex items-center gap-2.5">
      <svg class="animate-spin h-5 w-5 text-primary" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
      </svg>
      <span v-if="text" class="text-sm font-medium text-ink-600 dark:text-ink-300">{{ text }}</span>
    </div>
  </div>

  <!-- Full page loading -->
  <div v-else-if="type === 'page'" class="flex flex-col items-center justify-center py-20">
    <div class="relative">
      <div class="w-12 h-12 rounded-full border-4 border-surface-200 dark:border-ink-700" />
      <div class="absolute top-0 left-0 w-12 h-12 rounded-full border-4 border-transparent border-t-primary animate-spin" />
    </div>
    <p v-if="text" class="mt-4 text-sm font-medium text-ink-500 dark:text-ink-400">{{ text }}</p>
  </div>

  <!-- Skeleton rows -->
  <div v-else-if="type === 'skeleton'" class="space-y-3" :class="wrapperClass">
    <div
      v-for="i in rows"
      :key="i"
      class="skeleton"
      :class="rowClass"
      :style="{ animationDelay: (i - 1) * 100 + 'ms' }"
    />
  </div>

  <!-- Skeleton cards -->
  <div v-else-if="type === 'cards'" class="grid gap-4" :class="gridClass">
    <div
      v-for="i in rows"
      :key="i"
      class="rounded-xl border border-surface-200 dark:border-ink-800 bg-card p-4 space-y-3"
    >
      <!-- Card header skeleton -->
      <div class="flex items-center gap-3">
        <div class="skeleton w-10 h-10 rounded-lg shrink-0" />
        <div class="flex-1 space-y-2">
          <div class="skeleton h-4 rounded w-3/4" />
          <div class="skeleton h-3 rounded w-1/2" />
        </div>
      </div>
      <!-- Card body skeleton -->
      <div class="space-y-2">
        <div class="skeleton h-3 rounded w-full" />
        <div class="skeleton h-3 rounded w-5/6" />
      </div>
    </div>
  </div>

  <!-- Skeleton table -->
  <div v-else-if="type === 'table'" class="rounded-xl border border-border bg-card overflow-hidden">
    <!-- Table header -->
    <div class="flex border-b border-border bg-surface-50/50 dark:bg-ink-800/50">
      <div v-for="i in 5" :key="i" class="flex-1 px-4 py-3">
        <div class="skeleton h-3 rounded w-3/4" />
      </div>
    </div>
    <!-- Table rows -->
    <div
      v-for="i in rows"
      :key="i"
      class="flex border-b border-border/50 last:border-0"
    >
      <div v-for="j in 5" :key="j" class="flex-1 px-4 py-3">
        <div class="skeleton h-3 rounded" :style="{ width: (40 + Math.random() * 50) + '%' }" />
      </div>
    </div>
  </div>

  <!-- Default: inline dots -->
  <div v-else class="flex items-center gap-1.5" :class="wrapperClass">
    <div class="w-2 h-2 rounded-full bg-primary animate-bounce" style="animation-delay: 0ms" />
    <div class="w-2 h-2 rounded-full bg-primary animate-bounce" style="animation-delay: 150ms" />
    <div class="w-2 h-2 rounded-full bg-primary animate-bounce" style="animation-delay: 300ms" />
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  type: { type: String, default: 'spinner' },
  text: { type: String, default: '' },
  rows: { type: Number, default: 3 },
  gridCols: { type: Number, default: 3 },
  rowClass: { type: String, default: 'h-12 rounded-lg' },
  wrapperClass: { type: String, default: '' },
})

const gridClass = computed(() => {
  const cols = props.gridCols
  if (cols <= 1) return 'grid-cols-1'
  if (cols <= 2) return 'grid-cols-1 sm:grid-cols-2'
  if (cols <= 3) return 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'
  return 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4'
})
</script>

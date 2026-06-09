<template>
  <div class="flex flex-col items-center justify-center py-16 text-center">
    <!-- Icon -->
    <div class="size-16 mb-4 rounded-2xl bg-surface-100 dark:bg-ink-800 flex items-center justify-center">
      <slot name="icon">
        <svg v-if="!icon" class="size-8 text-ink-300 dark:text-ink-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
        <span v-else class="text-3xl">{{ icon }}</span>
      </slot>
    </div>

    <!-- Title -->
    <h3 class="text-base font-semibold text-ink-700 dark:text-ink-300 mb-1">
      <slot name="title">{{ title }}</slot>
    </h3>

    <!-- Description -->
    <p v-if="description || $slots.description" class="text-sm text-ink-400 dark:text-ink-500 max-w-xs mb-4">
      <slot name="description">{{ description }}</slot>
    </p>

    <!-- Action slot -->
    <div v-if="$slots.default">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
  icon: { type: String, default: '' },
})
</script>

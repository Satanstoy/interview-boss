<template>
  <div class="min-h-full">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">
      <!-- Header area -->
      <div v-if="title || $slots.header" class="mb-6">
        <div v-if="showBackButton" class="mb-3">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 text-sm font-medium text-ink-500 dark:text-ink-400 hover:text-ink-800 dark:hover:text-ink-200 transition-colors"
            @click="handleBack"
          >
            <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            {{ backText }}
          </button>
        </div>

        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div class="min-w-0">
            <h1 class="text-2xl font-bold tracking-tight text-ink-900 dark:text-ink-50">
              <slot name="title">{{ title }}</slot>
            </h1>
            <p v-if="description || $slots.description" class="mt-1.5 text-sm text-ink-500 dark:text-ink-400">
              <slot name="description">{{ description }}</slot>
            </p>
          </div>
          <div v-if="$slots.actions" class="flex items-center gap-2 shrink-0">
            <slot name="actions" />
          </div>
        </div>
      </div>

      <!-- Custom header slot (replaces default header entirely) -->
      <slot name="header" />

      <!-- Content area -->
      <slot />
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  showBackButton: { type: Boolean, default: false },
  backText: { type: String, default: '返回' },
})

const emit = defineEmits(['back'])

function handleBack() {
  emit('back')
}
</script>

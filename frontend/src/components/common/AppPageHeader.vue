<template>
  <div class="flex flex-col gap-4">
    <!-- Breadcrumb navigation -->
    <nav v-if="breadcrumbs && breadcrumbs.length" aria-label="breadcrumb">
      <ol class="flex items-center gap-1.5 text-sm text-ink-500 dark:text-ink-400">
        <li v-for="(crumb, idx) in breadcrumbs" :key="idx" class="flex items-center gap-1.5">
          <template v-if="idx > 0">
            <svg class="size-3.5 text-ink-300 dark:text-ink-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </template>
          <button
            v-if="crumb.to"
            type="button"
            class="hover:text-ink-800 dark:hover:text-ink-200 transition-colors bg-transparent border-none p-0 cursor-pointer"
            @click="handleNavigate(crumb)"
          >
            {{ crumb.label }}
          </button>
          <span v-else class="text-ink-800 dark:text-ink-200 font-medium">{{ crumb.label }}</span>
        </li>
      </ol>
    </nav>

    <!-- Header row -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div class="min-w-0">
        <!-- Back button -->
        <div v-if="showBackButton" class="mb-2">
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

        <!-- Title -->
        <h1 class="text-2xl font-bold tracking-tight text-ink-900 dark:text-ink-50">
          <slot name="title">{{ title }}</slot>
        </h1>

        <!-- Description -->
        <p v-if="description || $slots.description" class="mt-1.5 text-sm text-ink-500 dark:text-ink-400 max-w-2xl">
          <slot name="description">{{ description }}</slot>
        </p>
      </div>

      <!-- Actions -->
      <div v-if="$slots.actions" class="flex items-center gap-2 shrink-0">
        <slot name="actions" />
      </div>
    </div>

    <!-- Slot for additional header content (tabs, filters, etc.) -->
    <slot name="extra" />
  </div>
</template>

<script setup>
const props = defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  showBackButton: { type: Boolean, default: false },
  backText: { type: String, default: '返回' },
  breadcrumbs: { type: Array, default: () => [] },
})

const emit = defineEmits(['back', 'navigate'])

function handleBack() {
  emit('back')
}

function handleNavigate(crumb) {
  emit('navigate', crumb)
}
</script>

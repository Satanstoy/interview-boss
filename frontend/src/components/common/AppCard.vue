<template>
  <div
    :class="cn(
      'bg-card text-card-foreground rounded-xl border shadow-sm transition-colors duration-200',
      hover && 'hover:border-surface-300 dark:hover:border-ink-700 hover:shadow-md',
      noPadding ? '' : '',
      props.class
    )"
  >
    <!-- Header with title/description -->
    <div
      v-if="title || $slots.header || $slots['card-title']"
      :class="cn(
        'flex items-start justify-between gap-4',
        noPadding ? 'px-6 pt-6 pb-0' : 'px-6 pt-6 pb-0 border-b border-border/50 pb-4'
      )"
    >
      <div class="min-w-0 flex-1">
        <slot name="header">
          <h3 v-if="title" class="text-lg font-semibold leading-none tracking-tight text-ink-900 dark:text-ink-50">
            <slot name="card-title">{{ title }}</slot>
          </h3>
          <p v-if="description" class="mt-1.5 text-sm text-ink-500 dark:text-ink-400">
            {{ description }}
          </p>
        </slot>
      </div>
      <div v-if="$slots['card-action']" class="shrink-0">
        <slot name="card-action" />
      </div>
    </div>

    <!-- Content -->
    <div :class="cn(noPadding ? '' : 'px-6 py-5')">
      <slot />
    </div>

    <!-- Footer -->
    <div
      v-if="$slots.footer"
      :class="cn(
        'flex items-center gap-2',
        noPadding ? 'px-6 pb-6 pt-0' : 'px-6 py-4 border-t border-border/50'
      )"
    >
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup>
import { cn } from '@/lib/utils'

const props = defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  noPadding: { type: Boolean, default: false },
  hover: { type: Boolean, default: false },
  class: { type: [String, Object, Array], default: '' },
})
</script>

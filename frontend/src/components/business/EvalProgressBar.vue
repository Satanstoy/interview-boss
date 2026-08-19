<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: {
    type: Number,
    default: 0,
    validator: (v) => v >= 0 && v <= 100
  },
  variant: {
    type: String,
    default: 'default',
    validator: (v) => ['default', 'success', 'warning', 'error'].includes(v)
  },
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v)
  },
  showLabel: {
    type: Boolean,
    default: false
  },
  label: {
    type: String,
    default: ''
  }
})

const percentage = computed(() => Math.min(100, Math.max(0, props.value)))

const variantClasses = computed(() => {
  const variants = {
    default: 'bg-primary',
    success: 'bg-green-500',
    warning: 'bg-yellow-500',
    error: 'bg-red-500'
  }
  return variants[props.variant] || variants.default
})

const sizeClasses = computed(() => {
  const sizes = {
    sm: 'h-1',
    md: 'h-2',
    lg: 'h-3'
  }
  return sizes[props.size] || sizes.md
})

const displayLabel = computed(() => {
  if (props.label) return props.label
  return `${percentage.value}%`
})
</script>

<template>
  <div class="w-full">
    <div
      v-if="showLabel"
      class="flex justify-between items-center mb-1"
    >
      <span class="text-sm font-medium text-foreground">
        <slot name="label">{{ displayLabel }}</slot>
      </span>
      <span class="text-sm text-muted-foreground">
        {{ percentage }}%
      </span>
    </div>
    <div
      role="progressbar"
      :aria-valuenow="percentage"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="label || `进度 ${percentage}%`"
      :class="[
        'w-full rounded-full overflow-hidden bg-muted',
        sizeClasses
      ]"
    >
      <div
        :class="[
          'h-full rounded-full transition-all duration-300 ease-in-out',
          variantClasses
        ]"
        :style="{ width: percentage + '%' }"
      />
    </div>
  </div>
</template>

<style scoped>
/* 进度条动画 */
div[role="progressbar"] > div {
  transition: width 0.3s ease-in-out;
}
</style>
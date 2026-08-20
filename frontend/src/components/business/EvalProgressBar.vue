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
  },
  segments: {
    type: Array,
    default: null
  },
  showLegend: {
    type: Boolean,
    default: false
  }
})

const percentage = computed(() => Math.min(100, Math.max(0, props.value)))

const variantClasses = computed(() => {
  const variants = {
    default: 'bg-primary',
    success: 'bg-emerald-500',
    warning: 'bg-amber-500',
    error: 'bg-destructive'
  }
  return variants[props.variant] || variants.default
})

const sizeClasses = computed(() => {
  const sizes = {
    sm: 'h-2',
    md: 'h-2.5',
    lg: 'h-3'
  }
  return sizes[props.size] || sizes.md
})

const displayLabel = computed(() => {
  if (props.label) return props.label
  return `${percentage.value}%`
})

const isSegmented = computed(() => Array.isArray(props.segments) && props.segments.length > 0)

const segmentedTotal = computed(() => {
  if (!isSegmented.value) return 0
  return props.segments.reduce((sum, s) => sum + (Number(s.value) || 0), 0)
})

const segmentedAriaLabel = computed(() => {
  if (!isSegmented.value) return props.label || `进度 ${percentage.value}%`
  const parts = props.segments.map(s => `${s.label || s.key} ${s.value}`).join(' ')
  return `进度 ${parts} 共 ${segmentedTotal.value} 项`
})

const visibleSegments = computed(() => {
  if (!isSegmented.value) return []
  return props.segments.filter(s => (Number(s.value) || 0) > 0 && (Number(s.pct) || 0) > 0)
})
</script>

<template>
  <div class="w-full">
    <div
      v-if="showLabel"
      class="mb-1 flex items-center justify-between"
    >
      <span class="text-sm font-medium text-foreground">
        <slot name="label">{{ displayLabel }}</slot>
      </span>
      <span class="text-sm text-muted-foreground">
        {{ percentage }}%
      </span>
    </div>
    <!-- 分段模式 -->
    <div
      v-if="isSegmented"
      role="progressbar"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="100"
      :aria-label="segmentedAriaLabel"
      :class="['flex w-full overflow-hidden rounded-full bg-muted', sizeClasses]"
    >
      <div
        v-for="seg in visibleSegments"
        :key="seg.key"
        :class="['h-full transition-all duration-300 ease-in-out', seg.color || 'bg-primary']"
        :style="{ width: seg.pct + '%', ...(seg.pattern ? { backgroundImage: 'repeating-linear-gradient(135deg, transparent, transparent 4px, rgba(255,255,255,.35) 4px, rgba(255,255,255,.35) 8px)' } : {}) }"
        :title="`${seg.label || seg.key} ${seg.value} (${seg.pct}%)`"
      />
    </div>
    <!-- 单值模式（兼容旧调用） -->
    <div
      v-else
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
    <div v-if="isSegmented && showLegend" class="mt-1.5 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
      <span v-for="seg in segments" :key="seg.key" class="inline-flex items-center gap-1">
        <span :class="['size-2 rounded-full', seg.color || 'bg-primary']" />
        {{ seg.label || seg.key }} {{ seg.value }}
      </span>
    </div>
  </div>
</template>

<style scoped>
div[role="progressbar"] > div {
  transition: width 0.3s ease-in-out;
}
</style>

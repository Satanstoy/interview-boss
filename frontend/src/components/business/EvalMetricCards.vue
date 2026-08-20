<script setup>
defineProps({
  metrics: { type: Array, default: () => [] },
})

function valueLabel(metric) {
  if (metric.value == null) return '未完成'
  if (metric.unit === '%') return `${Math.round(Number(metric.value) * 100)}%`
  return `${metric.value}${metric.unit || ''}`
}

function statusLabel(status) {
  return { passed: '达标', poor: '不佳', unavailable: '未完成', available: '已记录' }[status] || '—'
}

function statusClass(status) {
  return {
    passed: 'text-emerald-700 bg-emerald-500/10',
    poor: 'text-amber-700 bg-amber-500/10',
    unavailable: 'text-muted-foreground bg-muted',
    available: 'text-muted-foreground bg-muted',
  }[status] || 'text-muted-foreground bg-muted'
}
</script>

<template>
  <div v-if="metrics.length" class="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
    <div v-for="metric in metrics" :key="metric.key" class="rounded-lg border border-border/60 bg-card px-3 py-2.5">
      <div class="flex items-start justify-between gap-2">
        <span class="text-xs text-muted-foreground">{{ metric.label }}</span>
        <span :class="['rounded-full px-1.5 py-0.5 text-[10px]', statusClass(metric.status)]">{{ statusLabel(metric.status) }}</span>
      </div>
      <div class="mt-1 text-lg font-semibold">{{ valueLabel(metric) }}</div>
      <div v-if="metric.threshold != null" class="mt-0.5 text-[11px] text-muted-foreground">目标 {{ metric.direction === 'lower' ? '≤' : '≥' }}{{ metric.unit === '%' ? `${Math.round(metric.threshold * 100)}%` : `${metric.threshold}${metric.unit || ''}` }}</div>
    </div>
  </div>
</template>

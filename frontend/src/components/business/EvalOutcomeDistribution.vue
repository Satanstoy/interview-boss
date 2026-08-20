<script setup>
import { computed } from 'vue'
import EvalProgressBar from './EvalProgressBar.vue'

const props = defineProps({
  distribution: { type: Object, default: () => ({}) },
  compact: { type: Boolean, default: false },
  ariaLabel: { type: String, default: '评测结果分布' },
})

const emit = defineEmits(['select'])

const outcomes = [
  { key: 'failed', label: '失败', color: 'bg-destructive', text: 'text-destructive' },
  { key: 'poor', label: '不佳', color: 'bg-amber-500', text: 'text-amber-700' },
  { key: 'passed', label: '通过', color: 'bg-emerald-500', text: 'text-emerald-700' },
  { key: 'pending', label: '未完成', color: 'bg-muted-foreground/30', text: 'text-muted-foreground', pattern: true },
]

const normalized = computed(() => {
  const total = Number(props.distribution?.total || 0)
  const values = outcomes.map(outcome => ({
    ...outcome,
    value: Number(props.distribution?.[outcome.key] || 0),
  }))
  if (!total) return values.map(item => ({ ...item, pct: 0 }))
  const lastVisibleIndex = values.reduce((last, item, index) => item.value > 0 ? index : last, -1)
  let used = 0
  return values.map((item, index) => {
    const pct = index === lastVisibleIndex
      ? Math.max(0, 100 - used)
      : Math.round(item.value / total * 100)
    used += pct
    return { ...item, pct }
  })
})

const segments = computed(() => normalized.value.map(outcome => ({
  key: outcome.key,
  label: outcome.label,
  value: outcome.value,
  pct: outcome.pct,
  color: outcome.color,
  pattern: outcome.pattern,
})))

function selectOutcome(key) {
  emit('select', key)
}
</script>

<template>
  <div :aria-label="ariaLabel" role="group">
    <EvalProgressBar :segments="segments" size="sm" :show-legend="false" />
    <div :class="compact ? 'mt-1' : 'mt-2'" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <button
        v-for="outcome in normalized"
        :key="outcome.key"
        type="button"
        :aria-label="`${outcome.label} ${outcome.value} 个 Case`"
        :class="['inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-muted', outcome.text]"
        @click="selectOutcome(outcome.key)"
      >
        <span :class="['size-2 rounded-full', outcome.color]" />
        {{ outcome.label }} {{ outcome.value }}<span v-if="!compact">（{{ outcome.pct }}%）</span>
      </button>
    </div>
  </div>
</template>

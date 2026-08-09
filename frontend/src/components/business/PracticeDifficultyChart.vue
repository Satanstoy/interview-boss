<template>
  <div
    ref="rootRef"
    class="lieflat-card flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm"
    :class="{ 'is-visible': isVisible }"
  >
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">{{ headline }}</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">
        每道横档代表 {{ rungUnit }} 题 · 深蓝 = 答对 · 浅蓝 = 待加强 · 以 60 分为通过线
      </p>
    </div>

    <button
      v-if="columns.length"
      type="button"
      class="mt-2 min-h-[220px] w-full flex-1 cursor-pointer text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label="各难度正确与待加强题量堆叠横档，点击重播动画"
      @click="replay"
    >
      <svg :key="replayKey" class="h-full w-full" viewBox="0 0 400 316" role="img">
        <line x1="32" y1="250" x2="368" y2="250" :stroke="palette.grid" stroke-width="1" />
        <g
          v-for="(column, columnIndex) in columns"
          :key="column.name"
          class="chart-mark"
          :style="{ animationDelay: `${columnIndex * 90}ms` }"
        >
          <line
            v-for="rung in column.rungs"
            :key="rung.index"
            :x1="column.x - 15 * rung.fraction"
            :x2="column.x + 15 * rung.fraction"
            :y1="rung.y"
            :y2="rung.y"
            :stroke="rung.kind === 'correct' ? palette.data : palette.faint"
            stroke-width="2.5"
            stroke-linecap="round"
          />
          <text
            :x="column.x"
            :y="column.topY - 13"
            text-anchor="middle"
            font-size="15"
            font-weight="800"
            :fill="palette.txt"
          >{{ column.count }}</text>
          <text
            :x="column.x"
            y="273"
            text-anchor="middle"
            font-size="11"
            font-weight="700"
            :fill="palette.label"
          >{{ column.name }}</text>
          <text
            :x="column.x"
            y="291"
            text-anchor="middle"
            font-size="9"
            font-weight="600"
            :fill="palette.muted"
          >答对 {{ column.correctCount }} · 待补 {{ column.needsWorkCount }}</text>
          <text
            :x="column.x"
            y="307"
            text-anchor="middle"
            font-size="9"
            font-weight="700"
            :fill="palette.label"
          >正确率 {{ formatRate(column.correctRate) }}</text>
        </g>
      </svg>
    </button>

    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      刷题后这里会显示难度分布
    </div>

    <p v-if="columns.length" class="mt-1 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
      Stacked Rungs · F7 · Practice records · Porcelain
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useTheme } from '@/composables/useTheme.js'
import { porcelain } from '@/utils/chartTokens.js'

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const ORDER = ['简单', '中等', '困难', '未标注']
const { isDark } = useTheme()
const rootRef = ref(null)
const isVisible = ref(false)
const replayKey = ref(0)
let observer = null

const palette = computed(() => porcelain(isDark.value))
const normalized = computed(() =>
  [...props.data]
    .filter((item) => Number(item.count) > 0)
    .map((item) => ({
      name: item.difficulty || '未标注',
      count: Number(item.count),
      correctRate: Math.min(100, Math.max(0, Number(item.correct_rate) || 0)),
      correctCount: Number.isFinite(Number(item.correct_count))
        ? Number(item.correct_count)
        : Math.round(Number(item.count) * (Number(item.correct_rate) || 0) / 100),
      needsWorkCount: Number.isFinite(Number(item.needs_work_count))
        ? Number(item.needs_work_count)
        : Number(item.count) - Math.round(Number(item.count) * (Number(item.correct_rate) || 0) / 100),
    }))
    .sort((a, b) => {
      const ai = ORDER.indexOf(a.name)
      const bi = ORDER.indexOf(b.name)
      return (ai === -1 ? ORDER.length : ai) - (bi === -1 ? ORDER.length : bi)
    }),
)
const maxCount = computed(() => Math.max(...normalized.value.map((item) => item.count), 1))

function niceUnit(maxValue) {
  if (maxValue <= 34) return 1
  const rough = maxValue / 34
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const normalizedValue = rough / magnitude
  const step = normalizedValue <= 1 ? 1 : normalizedValue <= 2 ? 2 : normalizedValue <= 5 ? 5 : 10
  return step * magnitude
}

const rungUnit = computed(() => niceUnit(maxCount.value))
const columns = computed(() => {
  const count = normalized.value.length
  const gap = count > 1 ? 300 / (count - 1) : 0
  const maxVisualRows = Math.max(...normalized.value.map((item) =>
    Math.ceil(item.correctCount / rungUnit.value)
      + Math.ceil(item.needsWorkCount / rungUnit.value)
      + 1,
  ), 1)
  const stepY = Math.min(5.4, 176 / maxVisualRows)

  return normalized.value.map((item, index) => {
    const buildSegment = (value, offset, kind) => {
      const exactRungs = value / rungUnit.value
      return Array.from({ length: Math.ceil(exactRungs) }, (_, rungIndex) => ({
        index: `${kind}-${rungIndex}`,
        y: 244 - (offset + rungIndex) * stepY,
        fraction: Math.min(1, exactRungs - rungIndex),
        kind,
      }))
    }
    const correctSlots = Math.ceil(item.correctCount / rungUnit.value)
    const correctRungs = buildSegment(item.correctCount, 0, 'correct')
    const needsWorkRungs = buildSegment(item.needsWorkCount, correctSlots + 1, 'needs-work')
    const rungs = [...correctRungs, ...needsWorkRungs]
    return {
      ...item,
      x: count === 1 ? 200 : 50 + gap * index,
      topY: rungs.length ? Math.min(...rungs.map((rung) => rung.y)) : 244,
      rungs,
    }
  })
})

const headline = computed(() => {
  const priority = [...normalized.value].sort((a, b) => a.correctRate - b.correctRate)[0]
  if (!priority) return '不同难度的练习证据'
  if (priority.count < 3) return `${priority.name}难度只有 ${priority.count} 次记录，先补足样本`
  if (priority.correctRate < 60) return `${priority.name}难度正确率 ${formatRate(priority.correctRate)}，是当前突破口`
  if (priority.correctRate < 80) return `${priority.name}难度正确率 ${formatRate(priority.correctRate)}，再巩固一轮`
  return '各难度正确率都已达到 80%，可以继续提高题目强度'
})

function formatRate(value) {
  return `${Number.isInteger(value) ? value : value.toFixed(1)}%`
}

function replay() {
  isVisible.value = true
  replayKey.value += 1
}

watch(() => props.data, replay, { deep: true })

onMounted(() => {
  if (!('IntersectionObserver' in window)) {
    isVisible.value = true
    return
  }
  observer = new IntersectionObserver(([entry]) => {
    if (entry.isIntersecting) {
      isVisible.value = true
      observer?.disconnect()
    }
  }, { threshold: 0.2 })
  if (rootRef.value) observer.observe(rootRef.value)
})

onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
.chart-mark {
  opacity: 0;
  transform: translateY(8px);
  transform-origin: center;
}

.is-visible .chart-mark {
  animation: rung-in 760ms cubic-bezier(0.165, 0.84, 0.44, 1) both;
}

@keyframes rung-in {
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .chart-mark,
  .is-visible .chart-mark {
    animation: none;
    opacity: 1;
    transform: none;
  }
}
</style>

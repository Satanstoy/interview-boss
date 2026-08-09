<template>
  <div
    ref="rootRef"
    class="heat-card flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm"
    :class="{ 'is-visible': isVisible }"
  >
    <div class="flex items-start justify-between gap-4">
      <div>
        <h3 class="text-sm font-semibold text-card-foreground">{{ headline }}</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          {{ momentumSummary }} · 每格 = 一天 · 颜色越深 = 练习越多
        </p>
      </div>
      <span
        v-if="totalCount > 0"
        class="shrink-0 rounded-full border border-border bg-muted/40 px-2.5 py-0.5 text-xs font-semibold text-foreground"
      >近 14 天 {{ recent14Count }} 题</span>
    </div>

    <div v-if="cells.length && totalCount > 0" class="mt-3 min-h-[190px] w-full flex-1 overflow-x-auto custom-scrollbar">
      <div class="relative min-w-[720px]">
        <svg
          :key="replayKey"
          class="h-full w-full overflow-visible"
          viewBox="0 0 800 205"
          role="img"
          aria-label="近一年每日练习日历热力图"
          @click="onChartClick"
        >
          <rect x="0" y="0" width="800" height="250" fill="transparent" />

          <text
            v-for="label in monthLabels"
            :key="label.key"
            :x="label.x"
            y="17"
            font-size="9"
            font-weight="700"
            letter-spacing="1"
            :fill="palette.muted"
          >{{ label.text }}</text>

          <text
            v-for="label in weekdayLabels"
            :key="label.text"
            x="42"
            :y="label.y"
            text-anchor="end"
            font-size="8"
            font-weight="700"
            :fill="palette.muted"
          >{{ label.text }}</text>

          <rect
            v-if="recentWindowBounds"
            :x="recentWindowBounds.x"
            :y="recentWindowBounds.y"
            :width="recentWindowBounds.width"
            :height="recentWindowBounds.height"
            rx="8"
            fill="none"
            :stroke="palette.label"
            stroke-width="1"
            stroke-dasharray="3 4"
          />
          <text
            v-if="recentWindowBounds"
            :x="recentWindowBounds.x + recentWindowBounds.width / 2"
            :y="recentWindowBounds.y + recentWindowBounds.height + 12"
            text-anchor="middle"
            font-size="8"
            font-weight="700"
            letter-spacing="0.8"
            :fill="palette.label"
          >最近 14 天</text>

          <g v-for="cell in cells" :key="cell.date" class="day-cell">
            <rect
              :x="cell.x"
              :y="cell.y"
              :width="cellSize"
              :height="cellSize"
              rx="3.5"
              :fill="cell.color"
              :stroke="cell.isPeak ? palette.hero : palette.grid"
              :stroke-width="cell.isPeak ? 1.5 : 0.7"
              tabindex="0"
              class="cursor-pointer outline-none"
              :style="{ animationDelay: `${cell.delay}ms` }"
              :aria-label="`${cell.date}，练习 ${cell.count} 题${cell.avgScore ? `，平均 ${cell.avgScore} 分` : ''}`"
              @mouseenter="showDay(cell.index)"
              @mouseleave="hideDay(cell.index)"
              @focus="showDay(cell.index)"
              @blur="hideDay(cell.index)"
              @click.stop="pinDay(cell.index)"
            />
            <circle
              v-if="cell.isPeak"
              :cx="cell.x + cellSize / 2"
              :cy="cell.y + cellSize / 2"
              :r="cellSize / 2 + 3"
              fill="none"
              :stroke="palette.hero"
              stroke-width="1"
              stroke-dasharray="2 3"
              class="peak-ring"
            />
          </g>

          <g transform="translate(580 179)">
            <text x="0" y="9" font-size="8" font-weight="600" :fill="palette.muted">少</text>
            <rect
              v-for="(color, index) in legendColors"
              :key="color"
              :x="24 + index * 22"
              y="0"
              width="16"
              height="16"
              rx="3"
              :fill="color"
              :stroke="palette.grid"
              stroke-width="0.7"
            />
            <text x="140" y="9" font-size="8" font-weight="600" :fill="palette.muted">多</text>
          </g>

          <text
            x="48"
            y="188"
            font-size="8"
            font-weight="600"
            letter-spacing="1.1"
            :fill="palette.muted"
          >CALENDAR HEAT · ONE CELL = ONE DAY · PORCELAIN</text>
        </svg>

        <div
          v-if="activeDay"
          class="pointer-events-none absolute z-10 min-w-36 -translate-x-1/2 rounded-lg border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md"
          :style="tooltipStyle"
          role="status"
        >
          <p class="font-semibold">{{ activeDay.date }}</p>
          <p class="mt-0.5 text-muted-foreground">
            练习 {{ activeDay.count }} 题<span v-if="activeDay.avgScore"> · 平均 {{ activeDay.avgScore }} 分</span>
          </p>
          <p v-if="pinnedIndex === activeDay.index" class="mt-1 text-[10px] text-muted-foreground">已固定 · 点击空白处取消</p>
        </div>
      </div>
    </div>

    <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
      <p class="text-sm text-muted-foreground">还没有练习记录</p>
      <Button variant="outline" size="sm" @click="goPractice">去刷一题，点亮第一格</Button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/composables/useTheme.js'
import { porcelain, RAMP, RAMP_DARK } from '@/utils/chartTokens.js'

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const router = useRouter()
const { isDark } = useTheme()
const rootRef = ref(null)
const isVisible = ref(false)
const replayKey = ref(0)
const hoverIndex = ref(null)
const pinnedIndex = ref(null)
let observer = null

const cellSize = 10
const xStep = 13.5
const yStep = 18
const xStart = 58
const yStart = 30
const palette = computed(() => porcelain(isDark.value))
const totalCount = computed(() => props.data.reduce((sum, day) => sum + (Number(day.count) || 0), 0))
const maxCount = computed(() => Math.max(...props.data.map((day) => Number(day.count) || 0), 1))
const recent14Count = computed(() => props.data.slice(-14).reduce((sum, day) => sum + (Number(day.count) || 0), 0))
const previous14Count = computed(() => props.data.slice(-28, -14).reduce((sum, day) => sum + (Number(day.count) || 0), 0))
const momentumDelta = computed(() => recent14Count.value - previous14Count.value)
const legendColors = computed(() => {
  const ramp = isDark.value ? RAMP_DARK : RAMP
  return [palette.value.grid, ramp[1], ramp[2], ramp[3], ramp[4]]
})

function mondayIndex(date) {
  return (date.getDay() + 6) % 7
}

const cells = computed(() => {
  const source = props.data.slice(-365)
  if (!source.length) return []
  const firstDate = new Date(`${source[0].date}T00:00:00`)
  const firstDayOffset = mondayIndex(firstDate)
  const ramp = isDark.value ? RAMP_DARK : RAMP
  const peak = Math.max(...source.map((day) => Number(day.count) || 0), 0)

  return source.map((day, index) => {
    const count = Number(day.count) || 0
    const slot = firstDayOffset + index
    const level = count === 0 ? 0 : Math.max(1, Math.min(4, Math.ceil(count / maxCount.value * 4)))
    return {
      index,
      date: day.date,
      count,
      avgScore: Number(day.avg_score) || 0,
      week: Math.floor(slot / 7),
      weekday: slot % 7,
      x: xStart + Math.floor(slot / 7) * xStep,
      y: yStart + (slot % 7) * yStep,
      color: count === 0 ? palette.value.grid : ramp[level],
      isPeak: count > 0 && count === peak,
      delay: Math.floor(slot / 7) * 12 + (slot % 7) * 4,
    }
  })
})

const weekdayLabels = [
  { text: '周一', y: yStart + cellSize / 2 + 3 },
  { text: '周三', y: yStart + yStep * 2 + cellSize / 2 + 3 },
  { text: '周五', y: yStart + yStep * 4 + cellSize / 2 + 3 },
  { text: '周日', y: yStart + yStep * 6 + cellSize / 2 + 3 },
]

const monthLabels = computed(() => {
  const labels = []
  let lastMonth = null
  for (const cell of cells.value) {
    const date = new Date(`${cell.date}T00:00:00`)
    if (date.getMonth() !== lastMonth) {
      labels.push({ key: cell.date, x: cell.x, text: `${date.getMonth() + 1}月` })
      lastMonth = date.getMonth()
    }
  }
  return labels
})

const recentWindowBounds = computed(() => {
  const recent = cells.value.slice(-14)
  if (!recent.length) return null
  const minX = Math.min(...recent.map((cell) => cell.x)) - 4
  const maxX = Math.max(...recent.map((cell) => cell.x)) + cellSize + 4
  return { x: minX, y: yStart - 4, width: maxX - minX, height: yStep * 6 + cellSize + 8 }
})

const activeIndex = computed(() => pinnedIndex.value ?? hoverIndex.value)
const activeDay = computed(() => activeIndex.value == null ? null : cells.value[activeIndex.value])
const tooltipStyle = computed(() => {
  if (!activeDay.value) return {}
  const left = Math.min(88, Math.max(12, activeDay.value.x / 8))
  const top = Math.min(72, Math.max(5, activeDay.value.y / 2.5))
  return { left: `${left}%`, top: `${top}%` }
})
const headline = computed(() => {
  const activeDays = props.data.filter((day) => Number(day.count) > 0).length
  if (!activeDays) return '从今天开始，点亮第一天的准备记录'
  if (momentumDelta.value > 0) return `最近 14 天多练了 ${momentumDelta.value} 题，准备节奏在上升`
  if (momentumDelta.value < 0) return `最近 14 天少练了 ${Math.abs(momentumDelta.value)} 题，今天把节奏接回来`
  return recent14Count.value > 0
    ? `最近 14 天完成 ${recent14Count.value} 题，准备节奏保持稳定`
    : `近一年点亮了 ${activeDays} 个练习日`
})
const momentumSummary = computed(() => {
  if (previous14Count.value === 0 && recent14Count.value > 0) return `新的练习节奏已经开始`
  const sign = momentumDelta.value > 0 ? '+' : ''
  return `较前 14 天 ${sign}${momentumDelta.value} 题`
})

function showDay(index) { hoverIndex.value = index }
function hideDay(index) { if (hoverIndex.value === index) hoverIndex.value = null }
function pinDay(index) { pinnedIndex.value = pinnedIndex.value === index ? null : index }

function onChartClick() {
  if (pinnedIndex.value != null) {
    pinnedIndex.value = null
    return
  }
  isVisible.value = true
  replayKey.value += 1
}

function replay() {
  hoverIndex.value = null
  pinnedIndex.value = null
  isVisible.value = true
  replayKey.value += 1
}

function goPractice() { router.push({ name: 'practice' }) }

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
.day-cell > rect,
.day-cell > .peak-ring {
  opacity: 0;
  transform: scale(0.65);
  transform-box: fill-box;
  transform-origin: center;
}

.is-visible .day-cell > rect,
.is-visible .day-cell > .peak-ring {
  animation: heat-cell-in 560ms cubic-bezier(0.165, 0.84, 0.44, 1) both;
}

@keyframes heat-cell-in {
  to { opacity: 1; transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .day-cell > rect,
  .day-cell > .peak-ring,
  .is-visible .day-cell > rect,
  .is-visible .day-cell > .peak-ring {
    animation: none;
    opacity: 1;
    transform: none;
  }
}
</style>

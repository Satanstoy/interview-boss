<template>
  <div
    ref="rootRef"
    class="lieflat-card flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm"
    :class="{ 'is-visible': isVisible }"
  >
    <div class="flex items-start justify-between gap-4">
      <div>
        <h3 class="text-sm font-semibold text-card-foreground">{{ headline }}</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          {{ momentumSummary }} · 一根发丝 = 一天 · 高度 = 当天练习量
        </p>
      </div>
      <span
        v-if="totalCount > 0"
        class="shrink-0 rounded-full border border-border bg-muted/40 px-2.5 py-0.5 text-xs font-semibold text-foreground"
      >近 14 天 {{ recent14Count }} 题</span>
    </div>

    <div v-if="days.length && totalCount > 0" class="mt-3 min-h-[230px] w-full flex-1 overflow-x-auto custom-scrollbar">
      <div class="relative min-w-[720px]">
        <svg
          :key="replayKey"
          class="h-full w-full overflow-visible"
        viewBox="0 0 800 250"
        role="img"
        aria-label="近九十天每日练习量条码棒棒糖图"
        @click="onChartClick"
        >
          <rect x="0" y="0" width="800" height="250" fill="transparent" />
          <g v-if="days.length > 14">
            <line
              :x1="recentWindowX"
              y1="18"
              :x2="recentWindowX"
              y2="207"
              :stroke="palette.label"
              stroke-width="1"
              stroke-dasharray="3 4"
            />
            <text
              :x="recentWindowX + 5"
              y="13"
              font-size="8"
              font-weight="700"
              letter-spacing="0.8"
              :fill="palette.label"
            >最近 14 天</text>
          </g>
          <g v-for="day in days" :key="day.date" class="day-mark">
          <line
            :x1="day.x"
            y1="18"
            :x2="day.x"
            y2="204"
            :stroke="palette.grid"
            stroke-width="0.75"
          />
          <line
            :x1="day.x"
            :y1="day.y"
            :x2="day.x"
            :y2="day.stemEnd"
            :stroke="day.color"
            stroke-width="1.6"
            stroke-linecap="round"
            :style="{ animationDelay: `${day.index * 8}ms` }"
          />
          <circle
            :cx="day.x"
            :cy="day.y"
            :r="day.isPeak ? 4.5 : 2.8"
            :fill="day.weekend ? palette.card : day.color"
            :stroke="day.isPeak ? palette.hero : day.color"
            :stroke-width="day.weekend || day.isPeak ? 1.5 : 0"
            tabindex="0"
            class="cursor-pointer outline-none"
            :aria-label="`${day.date}，练习 ${day.count} 题${day.avgScore ? `，平均 ${day.avgScore} 分` : ''}`"
            @mouseenter="showDay(day.index)"
            @mouseleave="hideDay(day.index)"
            @focus="showDay(day.index)"
            @blur="hideDay(day.index)"
            @click.stop="pinDay(day.index)"
          />
          <text
            v-if="day.isPeak"
            :x="day.x"
            :y="Math.max(12, day.y - 11)"
            text-anchor="middle"
            font-size="9"
            font-weight="800"
            :fill="palette.txt"
          >{{ day.count }}</text>
          </g>
          <text
            v-for="label in monthLabels"
            :key="label.key"
            :x="label.x"
            y="226"
            font-size="9"
            font-weight="700"
            letter-spacing="1"
            :fill="palette.muted"
          >{{ label.text }}</text>
          <text
            x="400"
            y="246"
            text-anchor="middle"
            font-size="8"
            font-weight="600"
            letter-spacing="1.2"
            :fill="palette.muted"
          >ONE HAIRLINE = ONE CALENDAR DAY · TOP 3 LABELED</text>
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
      <Button variant="outline" size="sm" @click="goPractice">去刷一题，留下第一根刻度</Button>
    </div>

    <p v-if="days.length && totalCount > 0" class="mt-1 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
      Barcode Lollipop · L3 · Daily practice · Porcelain
    </p>
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

const palette = computed(() => porcelain(isDark.value))
const totalCount = computed(() => props.data.reduce((sum, day) => sum + (Number(day.count) || 0), 0))
const maxCount = computed(() => Math.max(...props.data.map((day) => Number(day.count) || 0), 1))
const recent14Count = computed(() =>
  props.data.slice(-14).reduce((sum, day) => sum + (Number(day.count) || 0), 0),
)
const previous14Count = computed(() =>
  props.data.slice(-28, -14).reduce((sum, day) => sum + (Number(day.count) || 0), 0),
)
const momentumDelta = computed(() => recent14Count.value - previous14Count.value)

function deterministic(index, salt) {
  return Math.abs(((index + 1) * 73856093) ^ (salt * 19349663)) % 1000 / 1000
}

function topPeakIndexes(values) {
  const peaks = []
  const ordered = [...values.keys()].sort((a, b) => values[b] - values[a])
  for (const index of ordered) {
    if (values[index] <= 0) break
    if (peaks.every((peak) => Math.abs(peak - index) >= 6)) peaks.push(index)
    if (peaks.length === 3) break
  }
  return peaks
}

const days = computed(() => {
  const source = props.data.slice(-90)
  const values = source.map((day) => Number(day.count) || 0)
  const peaks = topPeakIndexes(values)
  const ramp = isDark.value ? RAMP_DARK : RAMP
  const width = 760
  const step = source.length > 1 ? width / (source.length - 1) : 0

  return source.map((day, index) => {
    const count = Number(day.count) || 0
    const date = new Date(`${day.date}T00:00:00`)
    const level = count === 0 ? 0 : Math.max(1, Math.min(4, Math.ceil(count / maxCount.value * 4)))
    const y = 202 - count / maxCount.value * 158
    return {
      index,
      date: day.date,
      count,
      avgScore: Number(day.avg_score) || 0,
      weekend: date.getDay() === 0 || date.getDay() === 6,
      isPeak: peaks.includes(index),
      x: 20 + index * step,
      y,
      stemEnd: Math.min(205, y + 14 + deterministic(index, 9) * 25),
      color: count === 0 ? palette.value.grid : ramp[level],
    }
  })
})

const monthLabels = computed(() => {
  const labels = []
  let lastMonth = null
  for (const day of days.value) {
    const date = new Date(`${day.date}T00:00:00`)
    const month = date.getMonth()
    if (month !== lastMonth) {
      labels.push({ key: day.date, x: day.x, text: `${month + 1}月` })
      lastMonth = month
    }
  }
  return labels
})
const recentWindowX = computed(() => days.value[Math.max(0, days.value.length - 14)]?.x ?? 20)

const activeIndex = computed(() => pinnedIndex.value ?? hoverIndex.value)
const activeDay = computed(() => activeIndex.value == null ? null : days.value[activeIndex.value])
const tooltipStyle = computed(() => {
  if (!activeDay.value) return {}
  const left = Math.min(88, Math.max(12, activeDay.value.x / 8))
  const top = Math.min(72, Math.max(4, activeDay.value.y / 2.5))
  return { left: `${left}%`, top: `${top}%` }
})
const headline = computed(() => {
  const activeDays = props.data.filter((day) => Number(day.count) > 0).length
  if (!activeDays) return '从今天开始，留下第一条面试准备证据'
  if (momentumDelta.value > 0) return `最近 14 天多练了 ${momentumDelta.value} 题，准备节奏在上升`
  if (momentumDelta.value < 0) return `最近 14 天少练了 ${Math.abs(momentumDelta.value)} 题，今天把节奏接回来`
  return recent14Count.value > 0
    ? `最近 14 天完成 ${recent14Count.value} 题，准备节奏保持稳定`
    : `近 90 天留下了 ${activeDays} 个练习日`
})
const momentumSummary = computed(() => {
  if (previous14Count.value === 0 && recent14Count.value > 0) {
    return `最近 14 天完成 ${recent14Count.value} 题，新的节奏已经开始`
  }
  const sign = momentumDelta.value > 0 ? '+' : ''
  return `最近 14 天 ${recent14Count.value} 题 · 较前 14 天 ${sign}${momentumDelta.value}`
})

function showDay(index) {
  hoverIndex.value = index
}

function hideDay(index) {
  if (hoverIndex.value === index) hoverIndex.value = null
}

function pinDay(index) {
  pinnedIndex.value = pinnedIndex.value === index ? null : index
}

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

function goPractice() {
  router.push({ name: 'practice' })
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
.day-mark > line:nth-of-type(2),
.day-mark > circle,
.day-mark > text {
  opacity: 0;
  transform: translateY(8px);
  transform-origin: center;
}

.is-visible .day-mark > line:nth-of-type(2),
.is-visible .day-mark > circle,
.is-visible .day-mark > text {
  animation: barcode-in 680ms cubic-bezier(0.165, 0.84, 0.44, 1) both;
}

@keyframes barcode-in {
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .day-mark > line:nth-of-type(2),
  .day-mark > circle,
  .day-mark > text,
  .is-visible .day-mark > line:nth-of-type(2),
  .is-visible .day-mark > circle,
  .is-visible .day-mark > text {
    animation: none;
    opacity: 1;
    transform: none;
  }
}
</style>

<template>
  <div
    ref="rootRef"
    class="lieflat-card flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm"
    :class="{ 'is-visible': isVisible }"
  >
    <div v-if="rows.length" class="flex items-start justify-between gap-4">
      <div>
        <h3 class="text-sm font-semibold text-card-foreground">{{ headline }}</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          每根刻度代表 {{ tickUnit }} 次出现 · 每 5 根设一个读数点 · 按频次降序
        </p>
      </div>
      <span class="shrink-0 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        Top {{ rows.length }}
      </span>
    </div>

    <button
      v-if="rows.length"
      type="button"
      class="mt-2 min-h-[260px] w-full flex-1 cursor-pointer overflow-x-auto text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label="高频主题刻度队列，点击重播动画"
      @click="replay"
    >
      <svg :key="replayKey" class="h-full w-full min-w-[520px]" :viewBox="`0 0 560 ${chartHeight}`" role="img">
        <g
          v-for="(row, rowIndex) in rows"
          :key="row.name"
          class="chart-mark"
          :style="{ animationDelay: `${rowIndex * 80}ms` }"
        >
          <text
            x="128"
            :y="row.y + 4"
            text-anchor="end"
            font-size="11"
            font-weight="700"
            :fill="palette.label"
          >{{ shortName(row.name) }}</text>
          <line
            x1="142"
            :y1="row.y + 11"
            x2="492"
            :y2="row.y + 11"
            :stroke="palette.grid"
            stroke-width="1"
          />
          <g v-for="tick in row.ticks" :key="tick.index">
            <line
              :x1="tick.x"
              :y1="row.y + 11"
              :x2="tick.x"
              :y2="row.y + 11 - tick.height"
              :stroke="rowIndex === 0 ? palette.hero : palette.data"
              stroke-width="2"
              stroke-linecap="round"
            />
            <circle
              v-if="tick.index % 5 === 4"
              :cx="tick.x"
              :cy="row.y + 16"
              r="1.25"
              :fill="palette.faint"
            />
          </g>
          <text
            x="508"
            :y="row.y + 4"
            font-size="14"
            font-weight="800"
            :fill="palette.txt"
          >{{ row.value }}</text>
        </g>
        <text
          x="280"
          :y="chartHeight - 5"
          text-anchor="middle"
          font-size="9"
          font-weight="600"
          letter-spacing="1.2"
          :fill="palette.muted"
        >ONE TICK = {{ tickUnit }} MENTIONS · DOT = EVERY FIFTH</text>
      </svg>
    </button>

    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      还没有面经数据，导入面经后会显示岗位高频主题
    </div>

    <p v-if="rows.length" class="mt-1 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
      Tick Rows · F5 · Interview evidence · Porcelain
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

const { isDark } = useTheme()
const rootRef = ref(null)
const isVisible = ref(false)
const replayKey = ref(0)
let observer = null

const palette = computed(() => porcelain(isDark.value))
const sortedData = computed(() =>
  [...props.data]
    .filter((item) => Number(item.frequency) > 0)
    .sort((a, b) => Number(b.frequency) - Number(a.frequency))
    .slice(0, 8),
)
const maxFrequency = computed(() => Math.max(...sortedData.value.map((item) => Number(item.frequency)), 1))

function niceUnit(maxValue) {
  if (maxValue <= 44) return 1
  const rough = maxValue / 44
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const normalized = rough / magnitude
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return step * magnitude
}

const tickUnit = computed(() => niceUnit(maxFrequency.value))
const chartHeight = computed(() => Math.max(260, sortedData.value.length * 42 + 28))
const rows = computed(() => {
  const x0 = 146
  const available = 340
  const maxTicks = Math.max(maxFrequency.value / tickUnit.value, 1)
  const step = available / maxTicks

  return sortedData.value.map((item, rowIndex) => {
    const value = Number(item.frequency)
    const exactTicks = value / tickUnit.value
    const ticks = Array.from({ length: Math.ceil(exactTicks) }, (_, index) => {
      const fraction = Math.min(1, exactTicks - index)
      const jitter = ((index * 17 + rowIndex * 29) % 7) / 7
      return {
        index,
        x: x0 + (index + 0.5) * step,
        height: (9 + jitter * 7) * Math.max(0.35, fraction),
      }
    })
    return { name: item.topic, value, y: 30 + rowIndex * 42, ticks }
  })
})

const headline = computed(() => {
  const first = sortedData.value[0]
  return first ? `“${shortName(first.topic, 12)}”是当前最高频主题` : '岗位高频主题'
})

function shortName(name, limit = 14) {
  const text = String(name || '未命名')
  return text.length > limit ? `${text.slice(0, limit)}…` : text
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
  transform: translateX(-8px);
  transform-origin: center;
}

.is-visible .chart-mark {
  animation: tick-row-in 720ms cubic-bezier(0.165, 0.84, 0.44, 1) both;
}

@keyframes tick-row-in {
  to { opacity: 1; transform: translateX(0); }
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

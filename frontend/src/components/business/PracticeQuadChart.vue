<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div v-if="props.items.length" ref="chartRef" class="quad-chart-canvas min-h-[260px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      题库还没有主题数据
    </div>
    <div class="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
      <span v-for="q in orderedQuadrants" :key="q.key" class="flex items-center gap-1.5">
        <span class="inline-block h-2 w-2 rounded-[2px]" :style="{ background: q.color }" />
        {{ q.label }} · {{ q.hint }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import * as echarts from 'echarts/core'
import { ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, GraphicComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'
import { mapToQuadrant, heatMedian, QUADRANTS } from '@/utils/quadrant.js'

echarts.use([ScatterChart, GridComponent, TooltipComponent, GraphicComponent, CanvasRenderer])

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const chartRef = ref(null)

// 象限颜色（深色/浅色共用，图形组件不随主题变）
const QUAD_COLORS = {
  breakthrough: '#f43f5e',
  advantage: '#10b981',
  maintain: '#f59e0b',
  lowPriority: '#94a3b8',
}

const orderedQuadrants = computed(() => [
  { key: 'breakthrough', ...QUADRANTS.breakthrough, color: QUAD_COLORS.breakthrough },
  { key: 'advantage', ...QUADRANTS.advantage, color: QUAD_COLORS.advantage },
  { key: 'maintain', ...QUADRANTS.maintain, color: QUAD_COLORS.maintain },
  { key: 'lowPriority', ...QUADRANTS.lowPriority, color: QUAD_COLORS.lowPriority },
])

const SKILL_MAX = 100
const HEAT_MAX = computed(() => {
  const max = Math.max(...props.items.map(i => i.question_frequency || 0), 0)
  return max > 0 ? max : 10
})

// 每象限的 scatter 数据点（坐标：[skill, heat]）
function scatterData(items, median) {
  const byQuad = { breakthrough: [], advantage: [], maintain: [], lowPriority: [] }
  for (const item of items) {
    const m = mapToQuadrant(item, median)
    byQuad[m.quadrant].push({
      name: item.name,
      value: [m.skill, m.heat],
      item: item,
    })
  }
  return byQuad
}

const buildOption = (dark) => {
  const median = heatMedian(props.items)
  const byQuad = scatterData(props.items, median)
  const axisColor = dark ? '#8f8881' : '#a8a29e'
  const splitColor = dark ? '#2e2a27' : '#f1efe9'
  const labelColor = dark ? '#cfcac5' : '#4a4540'

  return {
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
      borderColor: dark ? '#574f49' : '#e8e4dd',
      textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
      formatter: (params) => {
        const d = params.data
        if (!d) return ''
        return `${d.name}<br/>岗位热度：${d.item?.question_frequency ?? d.value[1]} 次<br/>熟练度：${d.item?.average_score == null ? '未练' : d.item.average_score + ' 分'}`
      },
    },
    grid: { left: 8, right: 14, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      min: 0,
      max: SKILL_MAX,
      name: '熟练度 →',
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: HEAT_MAX.value,
      name: '岗位热度 →',
      nameTextStyle: { color: axisColor, fontSize: 10 },
      axisLabel: { color: axisColor, fontSize: 10 },
      splitLine: { lineStyle: { color: splitColor } },
    },
    // 四象限背景 + 标签（用 graphic，位置按网格百分比）
    graphic: buildQuadrantGraphics(dark),
    series: Object.keys(byQuad).map(key => ({
      name: QUADRANTS[key].label,
      type: 'scatter',
      data: byQuad[key],
      symbolSize: (val) => 10 + (val?.[1] ?? 0) / HEAT_MAX.value * 12,
      itemStyle: { color: QUAD_COLORS[key], opacity: 0.85 },
      label: {
        show: true,
        position: 'top',
        fontSize: 10,
        color: dark ? '#e7e5e2' : '#1a1816',
        formatter: (p) => (p.data.name?.length > 8 ? p.data.name.slice(0, 8) + '…' : p.data.name),
      },
      emphasis: { scale: 1.2 },
    })),
  }
}

// 用 graphic 画 4 个半透明象限矩形 + 标签文字
function buildQuadrantGraphics(dark) {
  const skillMid = 50 // x 方向 50% 分界（熟练度中位）
  const heatMid = 50 // y 方向 50% 分界（热度中位）
  const alpha = dark ? 0.06 : 0.08
  const labelStyle = { fontSize: 11, fontWeight: 600 }
  const quadrants = [
    { key: 'breakthrough', x: 0, y: 0, w: skillMid, h: heatMid, ...QUADRANTS.breakthrough }, // 左上
    { key: 'advantage', x: skillMid, y: 0, w: 100 - skillMid, h: heatMid, ...QUADRANTS.advantage }, // 右上
    { key: 'lowPriority', x: 0, y: heatMid, w: skillMid, h: 100 - heatMid, ...QUADRANTS.lowPriority }, // 左下
    { key: 'maintain', x: skillMid, y: heatMid, w: 100 - skillMid, h: 100 - heatMid, ...QUADRANTS.maintain }, // 右下
  ]
  return quadrants.flatMap(q => [
    {
      type: 'rect',
      left: q.x + '%', top: q.y + '%',
      right: (100 - q.x - q.w) + '%', bottom: (100 - q.y - q.h) + '%',
      style: { fill: QUAD_COLORS[q.key], opacity: alpha },
      silent: true,
    },
    {
      type: 'text',
      left: (q.x + 2) + '%', top: (q.y + 1) + '%',
      style: { text: q.label, fill: QUAD_COLORS[q.key], ...labelStyle },
      silent: true,
    },
  ])
}

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.items, refresh, { deep: true })
</script>

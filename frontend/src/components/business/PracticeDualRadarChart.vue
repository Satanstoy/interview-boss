<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">能力差距</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">外圈 = 岗位热度 · 内圈 = 我的熟练度 · 空当越大越该补</p>
    </div>
    <div v-if="topItems.length" ref="chartRef" class="dual-radar-canvas mt-2 min-h-[260px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      题库还没有主题数据
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'
import { porcelain, EASE } from '@/utils/chartTokens.js'

echarts.use([RadarChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const chartRef = ref(null)

function shortName(name) {
  return name.length > 6 ? `${name.slice(0, 6)}…` : name
}

// 热度 Top8（与技能星图同源，口径一致）
const topItems = computed(() =>
  [...props.items]
    .filter((i) => i.question_frequency > 0)
    .sort((a, b) => (b.question_frequency || 0) - (a.question_frequency || 0))
    .slice(0, 8),
)

const maxHeat = computed(() => Math.max(...topItems.value.map((i) => i.question_frequency || 0), 1))

const buildOption = (dark) => {
  const t = porcelain(dark)
  const items = topItems.value
  // 双线同轴：热度 ÷ maxHeat ×100 归一，熟练度 0-100 天然同轴
  return {
    ...EASE,
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
      formatter: (params) => {
        const item = items[params.dataIndex]
        if (!item) return ''
        const isHeat = params.seriesName === '岗位热度'
        return isHeat
          ? `${item.name}<br/>岗位热度：${item.question_frequency} 次`
          : `${item.name}<br/>熟练度：${item.proficiency == null ? '未练' : item.proficiency + '%'}`
      },
    },
    legend: {
      top: 0,
      textStyle: { color: t.label, fontSize: 11 },
      data: ['岗位热度', '我的熟练度'],
    },
    radar: {
      indicator: items.map((item) => ({ name: shortName(item.name), max: 100 })),
      radius: '68%',
      center: ['50%', '55%'],
      splitNumber: 3,
      axisName: { color: t.label, fontSize: 10 },
      splitLine: { lineStyle: { color: t.grid } },
      axisLine: { lineStyle: { color: t.grid } },
    },
    series: [
      {
        name: '岗位热度',
        type: 'radar',
        data: [
          {
            value: items.map((item) => Math.round((item.question_frequency / maxHeat.value) * 100)),
            areaStyle: { color: dark ? 'rgba(188,199,215,.14)' : 'rgba(112,150,209,.14)' },
            lineStyle: { color: dark ? '#BCC7D7' : '#7096D1', width: 2.5 },
            itemStyle: { color: dark ? '#BCC7D7' : '#7096D1' },
            symbolSize: 4,
          },
        ],
      },
      {
        name: '我的熟练度',
        type: 'radar',
        data: [
          {
            value: items.map((item) => item.proficiency ?? 0),
            areaStyle: { color: dark ? 'rgba(237,239,241,.08)' : 'rgba(8,31,92,.06)' },
            lineStyle: { color: t.hero, width: 2.5, type: 'dashed' },
            itemStyle: { color: t.hero },
            symbolSize: 4,
          },
        ],
      },
    ],
  }
}

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.items, refresh, { deep: true })
</script>

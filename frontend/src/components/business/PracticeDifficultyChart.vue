<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">难度分布</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">各难度练习次数与正确率</p>
    </div>
    <div v-if="props.data.length" ref="chartRef" class="mt-2 min-h-[220px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      刷题后这里会显示难度分布
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'
import { porcelain, porcelainTooltip, EASE } from '@/utils/chartTokens.js'

echarts.use([PieChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)

// 难度是有序数据：明度即难度（简单=浅蓝 → 困难=最深蓝），未标注用淡灰蓝
const ORDER = ['简单', '中等', '困难', '未标注']

const buildOption = (dark) => {
  const t = porcelain(dark)
  const sorted = [...props.data].sort((a, b) => {
    const ia = ORDER.indexOf(a.difficulty)
    const ib = ORDER.indexOf(b.difficulty)
    if (ia === -1 && ib === -1) return 0
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
  const data = sorted.map((item, i) => ({
    name: item.difficulty,
    value: item.count,
    // 简单 → 中等 → 困难 = 蓝阶明度递增（最浅→最深）；未标注 = 淡灰蓝
    itemStyle: {
      color: i === 3 ? t.track : [t.faint2, t.data2, t.hero, t.data][i] || t.data,
    },
  }))
  return {
    ...EASE,
    tooltip: {
      ...porcelainTooltip(dark),
      formatter: (params) => {
        const item = sorted[params.dataIndex]
        return `${params.name}: ${params.value} 次 · 正确率 ${item.correct_rate}%`
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '68%'],
        center: ['50%', '54%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 6, borderColor: dark ? '#0F2B66' : '#FFFFFF', borderWidth: 2 },
        label: {
          show: true,
          fontSize: 11,
          fontWeight: 700,
          color: dark ? '#EDEFF1' : t.txt,
          formatter: '{b} {c} 次',
        },
        labelLine: { show: true, length: 12, length2: 12 },
        data,
      },
    ],
  }
}

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>

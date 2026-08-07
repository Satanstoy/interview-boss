<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-card-foreground">刷题趋势</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">近 30 天练习量与平均分</p>
      </div>
    </div>
    <div v-if="totalCount > 0" ref="chartRef" class="mt-2 min-h-[220px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      还没有练习记录，趋势图将在刷题后出现
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'
import { porcelain, porcelainTooltip, EASE } from '@/utils/chartTokens.js'

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const totalCount = computed(() => props.data.reduce((sum, d) => sum + (d.count || 0), 0))

const buildOption = (dark) => {
  const t = porcelain(dark)
  return {
    ...EASE,
    tooltip: { ...porcelainTooltip(dark, 'axis') },
    legend: {
      top: 0,
      textStyle: { color: t.label, fontSize: 11 },
      data: ['练习次数', '平均分'],
    },
    grid: { left: 8, right: 8, top: 28, bottom: 0, containLabel: true },
    xAxis: {
      type: 'category',
      data: props.data.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: t.track } },
      axisLabel: { color: t.muted, fontSize: 10, interval: 6 },
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: t.grid } },
        axisLabel: { color: t.muted, fontSize: 10 },
      },
      {
        type: 'value',
        min: 0,
        max: 100,
        splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: 10 },
      },
    ],
    series: [
      {
        name: '练习次数',
        type: 'bar',
        data: props.data.map((d) => d.count),
        itemStyle: { color: t.data2, borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 14,
      },
      {
        name: '平均分',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: props.data.map((d) => d.avg_score || null),
        itemStyle: { color: t.hero },
        lineStyle: { color: t.hero, width: 2.5 },
        connectNulls: false,
        symbolSize: 5,
      },
    ],
  }
}

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>

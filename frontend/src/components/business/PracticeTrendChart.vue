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

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const totalCount = computed(() => props.data.reduce((sum, d) => sum + (d.count || 0), 0))

const buildOption = (dark) => ({
  tooltip: {
    trigger: 'axis',
    confine: true,
    backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: dark ? '#574f49' : '#e8e4dd',
    textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
  },
  legend: {
    top: 0,
    textStyle: { color: dark ? '#cfcac5' : '#4a4540', fontSize: 11 },
    data: ['练习次数', '平均分'],
  },
  grid: { left: 8, right: 8, top: 28, bottom: 0, containLabel: true },
  xAxis: {
    type: 'category',
    data: props.data.map((d) => d.date.slice(5)),
    axisLine: { lineStyle: { color: dark ? '#574f49' : '#e8e4dd' } },
    axisLabel: { color: dark ? '#8f8881' : '#a8a29e', fontSize: 10, interval: 6 },
    axisTick: { show: false },
  },
  yAxis: [
    {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: dark ? '#2e2a27' : '#f1efe9' } },
      axisLabel: { color: dark ? '#8f8881' : '#a8a29e', fontSize: 10 },
    },
    {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { show: false },
      axisLabel: { color: dark ? '#8f8881' : '#a8a29e', fontSize: 10 },
    },
  ],
  series: [
    {
      name: '练习次数',
      type: 'bar',
      data: props.data.map((d) => d.count),
      itemStyle: { color: '#10b981', borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 14,
    },
    {
      name: '平均分',
      type: 'line',
      yAxisIndex: 1,
      smooth: true,
      data: props.data.map((d) => d.avg_score || null),
      itemStyle: { color: '#6366f1' },
      lineStyle: { color: '#6366f1', width: 2 },
      connectNulls: false,
      symbolSize: 5,
    },
  ],
})

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>

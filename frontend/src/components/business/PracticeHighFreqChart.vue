<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div v-if="props.data.length" ref="chartRef" class="high-freq-canvas min-h-[260px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      还没有面经数据，导入面经后会显示岗位高频主题
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const maxFreq = Math.max(...props.data.map((d) => d.frequency || 0), 1)

const buildOption = (dark) => ({
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    confine: true,
    backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: dark ? '#574f49' : '#e8e4dd',
    textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
  },
  grid: { left: 8, right: 30, top: 8, bottom: 8, containLabel: true },
  xAxis: {
    type: 'value',
    min: 0,
    max: maxFreq,
    axisLabel: { color: dark ? '#8f8881' : '#a8a29e', fontSize: 10 },
    splitLine: { lineStyle: { color: dark ? '#2e2a27' : '#f1efe9' } },
  },
  yAxis: {
    type: 'category',
    // 反向：让频次最高在顶部
    data: props.data.map((d) => d.topic).reverse(),
    axisLabel: { color: dark ? '#e7e5e2' : '#111111', fontSize: 12, fontWeight: 600 },
    axisLine: { lineStyle: { color: dark ? '#574f49' : '#e8e4dd' } },
    axisTick: { show: false },
  },
  series: [
    {
      name: '被问次数',
      type: 'bar',
      data: props.data.map((d) => d.frequency).reverse(),
      itemStyle: {
        color: '#6366f1',
        borderRadius: [0, 4, 4, 0],
      },
      barMaxWidth: 18,
      label: {
        show: true,
        position: 'right',
        fontSize: 12,
        fontWeight: 600,
        color: dark ? '#e7e5e2' : '#111111',
        formatter: '{c}',
      },
    },
  ],
})

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh, { deep: true })
</script>

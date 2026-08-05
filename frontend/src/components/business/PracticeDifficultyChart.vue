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

echarts.use([PieChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const palette = ['#10b981', '#f59e0b', '#f43f5e', '#94a3b8']

const buildOption = (dark) => ({
  tooltip: {
    trigger: 'item',
    confine: true,
    backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: dark ? '#574f49' : '#e8e4dd',
    textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
    formatter: (params) => {
      const item = props.data[params.dataIndex]
      return `${params.name}: ${params.value} 次 · 正确率 ${item.correct_rate}%`
    },
  },
  series: [
    {
      type: 'pie',
      radius: ['35%', '68%'],
      center: ['50%', '54%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: dark ? '#1a1816' : '#faf9f7', borderWidth: 2 },
      label: {
        show: true,
        fontSize: 10,
        color: dark ? '#cfcac5' : '#4a4540',
        formatter: '{b}\n{c} 次',
      },
      labelLine: { show: true, length: 6, length2: 8 },
      data: props.data.map((item, i) => ({
        name: item.difficulty,
        value: item.count,
        itemStyle: { color: palette[i % palette.length] },
      })),
    },
  ],
})

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>

<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">主题熟练度</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">按主题的间隔复习熟练度</p>
    </div>
    <div v-if="props.data.length" ref="chartRef" class="mt-2 min-h-[240px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      用闪卡复习后这里会生成熟练度雷达
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useEChart } from '@/composables/useEChart.js'

echarts.use([RadarChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)

function shortName(name) {
  return name.length > 6 ? `${name.slice(0, 6)}…` : name
}

const buildOption = (dark) => ({
  tooltip: {
    trigger: 'item',
    confine: true,
    backgroundColor: dark ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    borderColor: dark ? '#574f49' : '#e8e4dd',
    textStyle: { color: dark ? '#e7e5e2' : '#4a4540', fontSize: 12 },
    formatter: (params) => `${params.name}: 熟练度 ${params.value}%`,
  },
  radar: {
    indicator: props.data.map((item) => ({ name: shortName(item.topic), max: 100 })),
    radius: '68%',
    center: ['50%', '55%'],
    axisName: { color: dark ? '#cfcac5' : '#4a4540', fontSize: 10 },
    splitLine: { lineStyle: { color: dark ? '#2e2a27' : '#f1efe9' } },
    splitArea: { areaStyle: { color: dark ? ['#1e1b19', '#221f1c'] : ['#faf9f7', '#f5f3ef'] } },
    axisLine: { lineStyle: { color: dark ? '#2e2a27' : '#f1efe9' } },
  },
  series: [
    {
      type: 'radar',
      data: [
        {
          name: '熟练度',
          value: props.data.map((item) => item.proficiency),
          areaStyle: { color: 'rgba(99, 102, 241, 0.25)' },
          lineStyle: { color: '#6366f1', width: 2 },
          itemStyle: { color: '#6366f1' },
          symbolSize: 4,
        },
      ],
    },
  ],
})

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh)
</script>

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
import { porcelain, porcelainTooltip, rampLevel, EASE } from '@/utils/chartTokens.js'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const maxFreq = Math.max(...props.data.map((d) => d.frequency || 0), 1)

const buildOption = (dark) => {
  const t = porcelain(dark)
  const total = props.data.length
  return {
    ...EASE,
    tooltip: { ...porcelainTooltip(dark, 'axis'), axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 30, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      min: 0,
      max: maxFreq,
      axisLabel: { color: t.muted, fontSize: 10 },
      splitLine: { lineStyle: { color: t.grid } },
    },
    yAxis: {
      type: 'category',
      // 反向：让频次最高在顶部
      data: props.data.map((d) => d.topic).reverse(),
      axisLabel: { color: t.txt, fontSize: 12, fontWeight: 600 },
      axisLine: { lineStyle: { color: t.track } },
      axisTick: { show: false },
    },
    series: [
      {
        name: '被问次数',
        type: 'bar',
        // 排名数据：明度即排名（第一名最深 → 最后一名最浅）
        data: props.data.map((d, i) => ({
          value: d.frequency,
          itemStyle: { color: rampLevel(total - 1 - i, dark) },
        })).reverse(),
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        barMaxWidth: 18,
        label: {
          show: true,
          position: 'right',
          fontSize: 12,
          fontWeight: 700,
          color: t.txt,
          formatter: '{c}',
        },
      },
    ],
  }
}

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh, { deep: true })
</script>

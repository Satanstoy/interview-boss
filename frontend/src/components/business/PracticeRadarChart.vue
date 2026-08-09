<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">{{ headline }}</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">当前目标岗位 · SRS 熟练度 · 最需要巩固的最多 8 个主题</p>
    </div>
    <div v-if="chartData.length" ref="chartRef" class="mt-2 min-h-[240px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      用闪卡复习后这里会生成熟练度雷达
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
import { porcelain, porcelainTooltip, EASE } from '@/utils/chartTokens.js'

echarts.use([RadarChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const chartData = computed(() =>
  [...props.data]
    .filter((item) => Number.isFinite(Number(item.proficiency)))
    .sort((a, b) => Number(a.proficiency) - Number(b.proficiency))
    .slice(0, 8),
)
const weakestTopic = computed(() => chartData.value[0] || null)
const headline = computed(() => {
  const weakest = weakestTopic.value
  if (!weakest) return '当前岗位的薄弱主题'
  if (Number(weakest.proficiency) >= 80) return '已练主题整体稳定，可以扩展新的考点'
  return `“${shortName(weakest.topic)}”熟练度最低，优先复习`
})

function shortName(name) {
  return name.length > 6 ? `${name.slice(0, 6)}…` : name
}

const buildOption = (dark) => {
  const t = porcelain(dark)
  return {
    ...EASE,
    tooltip: {
      ...porcelainTooltip(dark),
      renderMode: 'richText',
      formatter: () => chartData.value
        .map((item) => `${item.topic}  ${Math.round(Number(item.proficiency))}%`)
        .join('\n'),
    },
    radar: {
      indicator: chartData.value.map((item) => ({ name: shortName(item.topic), max: 100 })),
      radius: '68%',
      center: ['50%', '55%'],
      splitNumber: 3,
      axisName: { color: t.label, fontSize: 10 },
      splitLine: { lineStyle: { color: t.grid } },
      axisLine: { lineStyle: { color: t.grid } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            name: '熟练度',
            value: chartData.value.map((item) => item.proficiency),
            areaStyle: { color: dark ? 'rgba(237,239,241,.16)' : 'rgba(51,78,172,.16)' },
            lineStyle: { color: t.data, width: 2.5 },
            itemStyle: { color: t.data },
            symbolSize: 4,
          },
        ],
      },
    ],
  }
}

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh, { deep: true })
</script>

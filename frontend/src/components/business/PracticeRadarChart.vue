<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">{{ headline }}</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">实线 = 我的熟练度 · 虚线 = 70% 稳定线 · 越靠中心越该优先补</p>
    </div>
    <div v-if="chartData.length" ref="chartRef" class="mt-2 min-h-[240px] w-full flex-1" style="min-width: 0;" />
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      用闪卡复习后这里会生成熟练度雷达
    </div>
    <p v-if="weakestTopic" class="mt-1 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground">
      Ability radar · current position · priority = lowest SRS proficiency
    </p>
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
import { isReferenceTopic } from '@/utils/insightTopics.js'

echarts.use([RadarChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const chartRef = ref(null)
const chartData = computed(() =>
  [...props.data]
    .filter((item) => isReferenceTopic(item.topic) && Number.isFinite(Number(item.proficiency)))
    .sort((a, b) => Number(a.proficiency) - Number(b.proficiency))
    .slice(0, 8),
)
const weakestTopic = computed(() => chartData.value[0] || null)
const headline = computed(() => {
  const weakest = weakestTopic.value
  if (!weakest) return '当前岗位的薄弱主题'
  if (Number(weakest.proficiency) >= 80) return '已练主题整体稳定，可以扩展新的考点'
  return `“${weakest.topic}”熟练度最低，优先复习`
})

function wrapName(name, maxChars = 7) {
  const chars = Array.from(name)
  if (chars.length <= maxChars) return name
  const lineCount = Math.ceil(chars.length / maxChars)
  const lineLength = Math.ceil(chars.length / lineCount)
  const lines = []
  for (let index = 0; index < chars.length; index += lineLength) {
    lines.push(chars.slice(index, index + lineLength).join(''))
  }
  return lines.join('\n')
}

const buildOption = (dark) => {
  const t = porcelain(dark)
  return {
    ...EASE,
    tooltip: {
      ...porcelainTooltip(dark),
      renderMode: 'richText',
      formatter: () => ['当前岗位能力证据', ...chartData.value
        .map((item) => `${item.topic}  ${Math.round(Number(item.proficiency))}%`)]
        .join('\n'),
    },
    radar: {
      indicator: chartData.value.map((item) => ({ name: item.topic, max: 100 })),
      radius: '68%',
      center: ['50%', '55%'],
      splitNumber: 5,
      splitArea: { show: false },
      axisName: {
        color: t.label,
        fontSize: 10,
        formatter: (name) => {
          const item = chartData.value.find((entry) => entry.topic === name)
          return item ? `{name|${wrapName(name)}}\n{value|${Math.round(Number(item.proficiency))}%}` : wrapName(name)
        },
        rich: {
          name: { color: t.label, fontSize: 10, fontWeight: 600, lineHeight: 14 },
          value: { color: t.hero, fontSize: 9, fontWeight: 800, lineHeight: 12 },
        },
      },
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
            areaStyle: { color: dark ? 'rgba(112,150,209,.24)' : 'rgba(51,78,172,.16)' },
            lineStyle: { color: t.data, width: 2.5 },
            itemStyle: { color: t.data },
            symbolSize: 4,
          },
          {
            name: '稳定线',
            value: chartData.value.map(() => 70),
            areaStyle: { color: 'transparent' },
            lineStyle: { color: t.muted, width: 1.2, type: 'dashed' },
            itemStyle: { color: t.muted },
            symbol: 'none',
          },
        ],
      },
    ],
  }
}

const { refresh } = useEChart(chartRef, buildOption)
watch(() => props.data, refresh, { deep: true })
</script>

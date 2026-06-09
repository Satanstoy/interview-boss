<template>
  <div class="rounded-xl border border-border bg-card shadow-sm">
    <div class="flex items-center justify-between border-b border-border px-4 py-3">
      <h3 class="text-sm font-semibold text-card-foreground flex items-center gap-2">
        <div class="w-6 h-6 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center">
          <svg class="w-3.5 h-3.5 text-violet-600 dark:text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" /></svg>
        </div>
        考点分布
      </h3>
    </div>
    <div class="p-4">
      <div v-if="masterBank.length === 0" class="w-full h-[200px] flex items-center justify-center text-ink-400 dark:text-ink-500 text-xs">暂无数据</div>
      <div v-else ref="chartRef" class="w-full h-[300px]" style="min-width: 0;"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTheme } from '@/composables/useTheme.js'

echarts.use([PieChart, TooltipComponent, CanvasRenderer])

const { isDark } = useTheme()

const props = defineProps({
  masterBank: { type: Array, default: () => [] }
})

const chartRef = ref(null)
let myChart = null
let resizeObserver = null

const updateDistributionChart = () => {
  if (!myChart || !props.masterBank.length) return
  const cat1Map = {}
  props.masterBank.forEach(item => {
    const c1 = (item.cat1 && item.cat1 !== '未分类(API漏标)') ? item.cat1 : '其他/未分类'
    cat1Map[c1] = (cat1Map[c1] || 0) + 1
  })
  const pieData = Object.keys(cat1Map).map(k => ({ name: k, value: cat1Map[k] })).sort((a, b) => b.value - a.value)

  myChart.setOption({
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: isDark.value ? 'rgba(45, 42, 39, 0.95)' : 'rgba(255, 255, 255, 0.95)',
      borderColor: isDark.value ? '#574f49' : '#e8e4dd',
      textStyle: { color: isDark.value ? '#e7e5e2' : '#4a4540', fontSize: 12 },
      formatter: '{b}: {c} 题 ({d}%)'
    },
    series: [{
      type: 'pie',
      radius: ['30%', '65%'],
      center: ['50%', '55%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: isDark.value ? '#1a1816' : '#faf9f7', borderWidth: 2 },
      label: { show: true, fontSize: 10, color: isDark.value ? '#cfcac5' : '#4a4540', formatter: '{b}\n{d}%' },
      labelLine: { show: true, length: 6, length2: 10 },
      data: pieData
    }]
  }, true)
}

watch(() => props.masterBank, () => nextTick(() => {
  if (myChart) {
    myChart.resize()
    updateDistributionChart()
  }
}), { deep: true })

watch(isDark, () => {
  if (myChart) updateDistributionChart()
})

onMounted(() => {
  if (chartRef.value) {
    myChart = echarts.init(chartRef.value)
    let resizeTimeout = null
    resizeObserver = new ResizeObserver(() => {
      if (resizeTimeout) clearTimeout(resizeTimeout)
      resizeTimeout = setTimeout(() => {
        if (myChart) myChart.resize()
      }, 100)
    })
    resizeObserver.observe(chartRef.value)
    nextTick(updateDistributionChart)
  }
})

onUnmounted(() => {
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  if (myChart) { myChart.dispose(); myChart = null }
})
</script>

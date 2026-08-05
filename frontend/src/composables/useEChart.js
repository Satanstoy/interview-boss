import { nextTick, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { useTheme } from './useTheme.js'

/**
 * ECharts 生命周期封装：init / ResizeObserver / 主题切换 / dispose。
 * buildOption(dark) 返回完整 option；数据变化后调用 refresh() 重绘。
 */
export function useEChart(chartRef, buildOption) {
  const { isDark } = useTheme()
  let myChart = null
  let resizeObserver = null

  function refresh() {
    nextTick(() => {
      if (!myChart && chartRef.value) {
        myChart = echarts.init(chartRef.value)
        resizeObserver = new ResizeObserver(() => {
          if (myChart) myChart.resize()
        })
        resizeObserver.observe(chartRef.value)
      }
      if (myChart && buildOption) myChart.setOption(buildOption(isDark.value), true)
    })
  }

  watch(isDark, () => {
    if (myChart && buildOption) myChart.setOption(buildOption(isDark.value), true)
  })

  onMounted(refresh)
  onUnmounted(() => {
    if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
    }
    if (myChart) {
      myChart.dispose()
      myChart = null
    }
  })

  return { refresh }
}

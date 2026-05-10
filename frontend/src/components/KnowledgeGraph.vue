<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <p class="text-sm text-ink-500 dark:text-ink-400">
        共 <span class="font-semibold text-ink-700 dark:text-ink-300">{{ nodeCount }}</span> 个知识点，
        <span class="font-semibold text-ink-700 dark:text-ink-300">{{ linkCount }}</span> 条关联
      </p>
      <div class="flex gap-2 items-center">
        <span class="text-xs text-ink-400 dark:text-ink-500">拖拽节点可调整布局 | 点击节点跳转题库</span>
        <button @click="resetView" class="text-xs bg-surface-100 dark:bg-ink-800 text-ink-600 dark:text-ink-400 px-3 py-1.5 rounded-lg hover:bg-surface-200 dark:hover:bg-ink-700 transition">重置视图</button>
      </div>
    </div>

    <div v-if="isLoading" class="text-center py-16 text-ink-400 dark:text-ink-500 border-2 border-dashed border-surface-200 dark:border-ink-600 rounded-xl">
      <svg class="animate-spin h-8 w-8 text-violet-400 mx-auto mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
      <p>正在加载知识图谱...</p>
    </div>

    <div v-else-if="nodeCount === 0" class="text-center py-16 text-ink-400 dark:text-ink-500 border-2 border-dashed border-surface-200 dark:border-ink-600 rounded-xl">
      <p class="text-lg mb-1">暂无数据</p>
      <p class="text-sm">请先导入面经数据并重建题库。</p>
    </div>

    <div v-show="nodeCount > 0" ref="chartRef" class="w-full bg-white dark:bg-surface-800 rounded-xl border border-surface-200 dark:border-ink-600" style="height: 640px;"></div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer])
import { fetchKnowledgeGraph } from '../api/index.js'
import { useToast } from '../composables/useNotification.js'
import { useTheme } from '../composables/useTheme.js'

const toast = useToast()
const emit = defineEmits(['filter-by-tag', 'filter-by-category'])
const { isDark } = useTheme()

const chartRef = ref(null)
const isLoading = ref(false)
const nodeCount = ref(0)
const linkCount = ref(0)
let myChart = null
let resizeHandler = null

const CATEGORY_COLORS = [
  '#6366f1', '#f59e0b', '#10b981', '#ef4444', '#3b82f6', '#8b5cf6', '#ec4899'
]

const loadGraph = async () => {
  isLoading.value = true
  try {
    const data = await fetchKnowledgeGraph()
    nodeCount.value = data.nodes.length
    linkCount.value = data.links.length
    await nextTick()
    renderChart(data)
  } catch (e) {
    console.error('加载知识图谱失败', e)
    toast.error('加载知识图谱失败')
  } finally {
    isLoading.value = false
  }
}

const renderChart = ({ nodes, links, categories }) => {
  if (!chartRef.value) return
  if (myChart) myChart.dispose()
  myChart = echarts.init(chartRef.value)

  myChart.setOption({
    tooltip: {
      formatter: (params) => {
        if (params.dataType === 'node') {
          const d = params.data
          const typeLabel = d._type === 'category' ? '分类' : '标签'
          return `<strong>${d.name}</strong><br/>题目数: ${d._size}<br/>类型: ${typeLabel}`
        }
        if (params.dataType === 'edge') {
          return `${params.data._sourceName || ''} - ${params.data._targetName || ''}<br/>关联强度: ${params.data.weight}`
        }
        return ''
      }
    },
    legend: {
      data: categories.map(c => c.name),
      orient: 'vertical',
      right: 16,
      top: 16,
      textStyle: { fontSize: 11 }
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      zoom: 0.85,
      label: { show: true, formatter: '{b}' },
      categories: categories.map((c, i) => ({
        name: c.name,
        itemStyle: { color: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }
      })),
      data: nodes.map(n => ({
        id: n.id,
        name: n.name,
        category: n.category,
        symbolSize: n.type === 'category'
          ? Math.max(50, Math.sqrt(n.size) * 10)
          : Math.max(12, Math.sqrt(n.size) * 5),
        itemStyle: {
          borderColor: '#fff',
          borderWidth: n.type === 'category' ? 3 : 1,
          shadowBlur: n.type === 'category' ? 10 : 0,
          shadowColor: CATEGORY_COLORS[n.category % CATEGORY_COLORS.length] + '40'
        },
        label: {
          fontSize: n.type === 'category' ? 15 : 10,
          fontWeight: n.type === 'category' ? 'bold' : 'normal',
          show: n.type === 'category' || n.size >= 3
        },
        _type: n.type,
        _size: n.size
      })),
      links: links.map(l => ({
        source: l.source,
        target: l.target,
        weight: l.weight,
        _sourceName: l.source.split(':')[1] || l.source,
        _targetName: l.target.split(':')[1] || l.target,
        lineStyle: {
          width: Math.max(1, Math.sqrt(l.weight) * 1.2),
          curveness: 0.15,
          opacity: 0.5
        }
      })),
      force: {
        repulsion: [120, 400],
        edgeLength: [60, 200],
        gravity: 0.08,
        friction: 0.6
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 5, opacity: 0.9 },
        label: { fontSize: 14, fontWeight: 'bold' }
      },
      lineStyle: { color: '#aaa', curveness: 0.15 }
    }]
  })

  myChart.on('click', (params) => {
    if (params.dataType !== 'node') return
    const d = params.data
    if (d._type === 'category') {
      emit('filter-by-category', d.name)
    } else {
      emit('filter-by-tag', d.name)
    }
  })

  updateChartTheme()
}

const updateChartTheme = () => {
  if (!myChart) return
  const dark = isDark.value
  myChart.setOption({
    tooltip: {
      backgroundColor: dark ? '#1e293b' : '#fff',
      borderColor: dark ? '#334155' : '#e5e7eb',
      textStyle: { color: dark ? '#e2e8f0' : '#374151' }
    },
    legend: {
      textStyle: { color: dark ? '#cbd5e1' : '#374151' }
    },
    series: [{
      lineStyle: { color: dark ? '#64748b' : '#aaa' },
      links: myChart.getOption()?.series?.[0]?.links
        ? myChart.getOption().series[0].links.map(l => ({ ...l }))
        : undefined
    }]
  })
  // Update node border colors
  const opt = myChart.getOption()
  if (opt?.series?.[0]?.data) {
    const updatedData = opt.series[0].data.map(n => ({
      ...n,
      itemStyle: {
        ...n.itemStyle,
        borderColor: dark ? '#1e293b' : '#fff'
      }
    }))
    myChart.setOption({ series: [{ data: updatedData }] })
  }
}

watch(isDark, () => updateChartTheme())

const resetView = () => {
  if (myChart) {
    myChart.dispatchAction({ type: 'restore' })
  }
}

onMounted(() => {
  loadGraph()
  resizeHandler = () => myChart?.resize()
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeHandler)
  if (myChart) {
    myChart.dispose()
    myChart = null
  }
})
</script>

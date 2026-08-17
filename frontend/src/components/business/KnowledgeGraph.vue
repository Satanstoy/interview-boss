<template>
  <div :style="{ background: t.bg, color: t.txt }" class="overflow-hidden rounded-3xl">
    <div class="flex flex-col gap-3 px-5 pt-5 sm:flex-row sm:items-start sm:justify-between sm:px-7 sm:pt-7">
      <div>
        <h2 class="text-lg font-bold tracking-tight">{{ graphHeadline }}</h2>
        <p :style="{ color: t.faint }" class="mt-1 text-xs">
          {{ categoryCount }} 个主题自组织 · 节点面积 = 题目数 · 拖拽探索 · 悬停聚焦邻接关系
        </p>
      </div>
      <Button
        v-if="nodeCount > 0"
        variant="outline"
        size="sm"
        :style="{ borderColor: t.faint2, color: t.txt }"
        class="self-start bg-transparent hover:bg-[#0F2B66] hover:text-white"
        @click="resetView"
      >
        <RotateCcw class="h-3.5 w-3.5" />
        重播布局
      </Button>
    </div>

    <div v-if="isLoading" :style="{ color: t.faint }" class="flex min-h-[520px] flex-col items-center justify-center gap-3">
      <LoaderCircle class="h-7 w-7 animate-spin" />
      <p class="text-sm">正在组织知识关系…</p>
    </div>

    <div v-else-if="nodeCount === 0" :style="{ color: t.faint }" class="flex min-h-[520px] flex-col items-center justify-center gap-1 text-center">
      <p :style="{ color: t.txt }" class="text-base font-semibold">还没有形成知识网络</p>
      <p class="text-sm">请先导入面经数据并完成聚类。</p>
    </div>

    <div
      v-show="!isLoading && nodeCount > 0"
      ref="chartRef"
      class="w-full cursor-grab active:cursor-grabbing"
      style="height: 640px"
      aria-label="可拖拽的知识点力导向网络"
    />

    <div v-if="nodeCount > 0" :style="{ color: t.faint }" class="flex flex-wrap items-center justify-between gap-2 px-5 pb-5 text-[10px] font-medium uppercase tracking-[0.1em] sm:px-7 sm:pb-6">
      <span>Force Graph · B2 · Knowledge clusters · Porcelain</span>
      <span>{{ nodeCount }} nodes · {{ linkCount }} links</span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { LoaderCircle, RotateCcw } from '@lucide/vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Button } from '@/components/ui/button'
import { fetchKnowledgeGraph } from '@/api/index.js'
import { useToast } from '@/composables/useNotification.js'
import { PORCELAIN, RAMP_DARK } from '@/utils/chartTokens.js'

const t = PORCELAIN.dark

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

const emit = defineEmits(['filter-by-tag', 'filter-by-category'])
const toast = useToast()
const chartRef = ref(null)
const isLoading = ref(false)
const nodeCount = ref(0)
const linkCount = ref(0)
const categoryCount = ref(0)
let myChart = null
let resizeObserver = null
let currentOption = null
let emptyCanvasReplayBound = false

const graphHeadline = computed(() => {
  if (!nodeCount.value) return '知识点会在这里聚成星系'
  return `${nodeCount.value} 个知识点，沿 ${categoryCount.value} 个主题聚成网络`
})

function rampByImportance(value, maxValue, isHub) {
  if (isHub) return RAMP_DARK[4]
  const level = Math.max(0, Math.min(3, Math.ceil((value / Math.max(maxValue, 1)) * 4) - 1))
  return RAMP_DARK[level]
}

function buildOption({ nodes, links }) {
  const maxSize = Math.max(...nodes.map((node) => Number(node.size) || 0), 1)
  const dense = nodes.length > 80
  const sparse = nodes.length < 40

  return {
    animationDuration: 300,
    animationEasing: 'quarticOut',
    tooltip: {
      confine: true,
      backgroundColor: PORCELAIN.light.bg,
      borderWidth: 0,
      padding: [10, 14],
      textStyle: { color: PORCELAIN.light.txt, fontSize: 12 },
      formatter: (params) => {
        if (params.dataType === 'node') {
          const data = params.data
          const typeLabel = data._type === 'category' ? '主题' : '知识点'
          return `<strong>${data.name}</strong><br/>题目数：${data._size}<br/>类型：${typeLabel}`
        }
        if (params.dataType === 'edge') {
          return `${params.data._sourceName || ''} → ${params.data._targetName || ''}<br/>关联强度：${params.data.weight}`
        }
        return ''
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      zoom: dense ? 0.72 : sparse ? 0.86 : 0.88,
      left: sparse ? 40 : 10,
      right: sparse ? 40 : 10,
      top: sparse ? 40 : 10,
      bottom: sparse ? 40 : 10,
      force: {
        repulsion: dense ? 52 : sparse ? 230 : 112,
        edgeLength: dense ? [12, 54] : sparse ? [56, 128] : [32, 104],
        gravity: sparse ? 0.08 : 0.14,
        friction: sparse ? 0.34 : 0.24,
        layoutAnimation: true,
      },
      data: nodes.map((node) => {
        const value = Number(node.size) || 0
        const isHub = node.type === 'category'
        return {
          id: node.id,
          name: node.name,
          value,
          symbolSize: isHub
            ? Math.min(68, 18 + Math.sqrt(value) * 5.2)
            : Math.min(30, 4 + Math.sqrt(value) * 4.2),
          itemStyle: {
            color: rampByImportance(value, maxSize, isHub),
            borderColor: t.bg,
            borderWidth: isHub ? 2 : 0,
          },
          label: {
            show: isHub,
            position: isHub ? 'inside' : 'right',
            color: isHub ? t.bg : t.txt,
            fontSize: isHub ? 10 : 9,
            fontWeight: isHub ? 800 : 600,
            formatter: ({ name }) => name.length > 8 ? `${name.slice(0, 8)}…` : name,
          },
          _type: node.type,
          _size: value,
        }
      }),
      links: links.map((link) => ({
        source: link.source,
        target: link.target,
        weight: Number(link.weight) || 0,
        _sourceName: link.source.split(':')[1] || link.source,
        _targetName: link.target.split(':')[1] || link.target,
        lineStyle: {
          width: Math.max(0.7, Math.sqrt(Number(link.weight) || 0) * 0.8),
          color: t.faint2,
          opacity: 0.42,
          curveness: 0.08,
        },
      })),
      emphasis: {
        focus: 'adjacency',
        lineStyle: { color: t.txt, opacity: 0.95, width: 1.8 },
        label: { show: true, color: t.txt, position: 'right', fontSize: 10, fontWeight: 700 },
      },
      blur: {
        itemStyle: { opacity: 0.1 },
        lineStyle: { opacity: 0.03 },
        label: { show: false },
      },
      lineStyle: { color: t.faint2, opacity: 0.42, curveness: 0.08 },
    }],
  }
}

function bindChartEvents() {
  if (!myChart) return
  myChart.off('click')
  myChart.on('click', (params) => {
    if (params.dataType !== 'node') return
    if (params.data._type === 'category') emit('filter-by-category', params.data.name)
    else emit('filter-by-tag', params.data.name)
  })
  if (!emptyCanvasReplayBound) {
    myChart.getZr().on('click', (event) => {
      if (!event.target) resetView()
    })
    emptyCanvasReplayBound = true
  }
}

function renderChart(data) {
  if (!chartRef.value) return
  if (!myChart) myChart = echarts.init(chartRef.value)
  currentOption = buildOption(data)
  myChart.clear()
  myChart.setOption(currentOption)
  bindChartEvents()

  if (!resizeObserver) {
    resizeObserver = new ResizeObserver(() => myChart?.resize())
    resizeObserver.observe(chartRef.value)
  }
}

async function loadGraph() {
  isLoading.value = true
  try {
    const data = await fetchKnowledgeGraph()
    nodeCount.value = data.nodes.length
    linkCount.value = data.links.length
    categoryCount.value = data.categories.length
    await nextTick()
    if (nodeCount.value > 0) renderChart(data)
  } catch (error) {
    console.error('加载知识图谱失败', error)
    toast.error('加载知识图谱失败')
  } finally {
    isLoading.value = false
    await nextTick()
    myChart?.resize()
  }
}

function resetView() {
  if (!myChart || !currentOption) return
  myChart.clear()
  myChart.setOption(currentOption)
}

onMounted(loadGraph)

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (myChart) {
    myChart.dispose()
    myChart = null
  }
  emptyCanvasReplayBound = false
})
</script>

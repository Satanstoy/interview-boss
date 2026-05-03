<template>
  <div class="lg:col-span-1 bg-white p-4 lg:p-6 rounded-xl shadow-sm border border-gray-100 h-fit lg:sticky lg:top-8 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto custom-scrollbar">
    <h2 class="text-xl font-bold mb-5 text-gray-800">数据概览</h2>
    <button @click="$emit('refresh')" class="w-full bg-indigo-50 text-indigo-700 px-4 py-2 rounded-lg mb-5 hover:bg-indigo-100 transition text-sm font-medium">
      刷新
    </button>

    <div class="mb-6">
      <h3 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">考点分布</h3>
      <div v-if="masterBank.length > 0" ref="chartRef" class="w-full h-[260px] lg:h-[300px]"></div>
      <div v-else class="w-full h-[260px] lg:h-[300px] flex items-center justify-center text-gray-400 text-sm">暂无数据</div>
    </div>

    <div class="mb-6">
      <h3 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">热门技术栈</h3>
      <ul class="space-y-1.5">
        <li v-for="(count, tech) in analytics.tech_trends" :key="tech" class="flex justify-between items-center text-sm px-2 py-1 rounded hover:bg-gray-50">
          <span class="text-gray-700 break-all mr-2">{{ tech }}</span>
          <span class="text-gray-400 font-mono text-xs whitespace-nowrap bg-gray-100 px-2 py-0.5 rounded">{{ count }}</span>
        </li>
        <li v-if="!analytics.tech_trends || Object.keys(analytics.tech_trends).length === 0" class="text-gray-400 text-sm px-2">暂无数据</li>
      </ul>
    </div>

    <div>
      <h3 class="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-3">分类目录</h3>
      <ul class="space-y-1">
        <li
          @click="$emit('select-tag', '全部')"
          class="flex justify-between items-center text-sm cursor-pointer px-2 py-1.5 rounded-lg transition-colors border border-transparent"
          :class="selectedTag === '全部' ? 'bg-green-50 text-green-700 font-semibold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
        >
          <span>全部</span>
          <span class="text-gray-400 font-mono text-xs">{{ masterBank.length }}</span>
        </li>
        <li
          v-for="(count, topic) in popularTags" :key="topic"
          @click="$emit('select-tag', topic)"
          class="flex justify-between items-center text-sm cursor-pointer px-2 py-1.5 rounded-lg transition-colors border border-transparent group"
          :class="selectedTag === topic ? 'bg-green-50 text-green-700 font-semibold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
        >
          <span class="break-all mr-2 group-hover:text-green-600 transition-colors">{{ topic }}</span>
          <span class="text-gray-400 font-mono text-xs whitespace-nowrap group-hover:text-green-500">{{ count }}</span>
        </li>
        <li v-if="!popularTags || Object.keys(popularTags).length === 0" class="text-gray-400 text-sm px-2 py-1.5">暂无数据</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  analytics: { type: Object, default: () => ({ tech_trends: {} }) },
  masterBank: { type: Array, default: () => [] },
  popularTags: { type: Object, default: () => ({}) },
  selectedTag: { type: String, default: '全部' }
})

defineEmits(['refresh', 'select-tag'])

const chartRef = ref(null)
let myChart = null
let resizeHandler = null

const updateDistributionChart = () => {
  if (!myChart || !props.masterBank.length) return
  const cat1Map = {}
  props.masterBank.forEach(item => {
    const c1 = (item.cat1 && item.cat1 !== '未分类(API漏标)') ? item.cat1 : '其他/未分类'
    cat1Map[c1] = (cat1Map[c1] || 0) + 1
  })
  const pieData = Object.keys(cat1Map)
    .map(k => ({ name: k, value: cat1Map[k] }))
    .sort((a, b) => b.value - a.value)

  myChart.setOption({
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e5e7eb',
      textStyle: { color: '#374151' },
      formatter: '{b}: {c} 题 ({d}%)'
    },
    series: [{
      type: 'pie',
      radius: ['35%', '70%'],
      center: ['50%', '55%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
      label: { show: true, fontSize: 11, formatter: '{b}\n{d}%' },
      labelLine: { show: true, length: 8, length2: 12 },
      data: pieData
    }]
  }, true)
}

watch(() => props.masterBank, () => nextTick(updateDistributionChart), { deep: true })

onMounted(() => {
  if (chartRef.value) {
    myChart = echarts.init(chartRef.value)
    resizeHandler = () => myChart && myChart.resize()
    window.addEventListener('resize', resizeHandler)
    nextTick(updateDistributionChart)
  }
})

onUnmounted(() => {
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
  if (myChart) { myChart.dispose(); myChart = null }
})
</script>

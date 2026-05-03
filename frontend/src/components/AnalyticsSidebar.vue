<template>
  <div class="lg:col-span-1 bg-white p-4 lg:p-6 rounded-xl shadow-sm border border-gray-100 h-fit lg:sticky lg:top-8 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto custom-scrollbar">
    <h2 class="text-2xl font-bold mb-6">全局分析</h2>
    <button @click="$emit('refresh')" class="w-full bg-indigo-50 text-indigo-700 px-4 py-2 rounded mb-6 hover:bg-indigo-100 transition">
      刷新分析数据
    </button>

    <div class="mb-8">
      <h3 class="text-lg font-semibold text-gray-700 mb-3 border-l-4 border-purple-500 pl-2">考点分布 (精炼题库)</h3>
      <div ref="chartRef" class="w-full h-[320px]"></div>
    </div>

    <div class="mb-8">
      <h3 class="text-lg font-semibold text-gray-700 mb-3 border-l-4 border-blue-500 pl-2">热点技术栈 (JD)</h3>
      <ul class="space-y-2">
        <li v-for="(count, tech) in analytics.tech_trends" :key="tech" class="flex justify-between items-center text-sm px-2">
          <span class="bg-gray-100 px-2 py-1 rounded break-all mr-2">{{ tech }}</span>
          <span class="text-gray-500 font-mono whitespace-nowrap">{{ count }} 次</span>
        </li>
        <li v-if="!analytics.tech_trends || Object.keys(analytics.tech_trends).length === 0" class="text-gray-400 text-sm px-2">暂无数据</li>
      </ul>
    </div>

    <div>
      <h3 class="text-lg font-semibold text-gray-700 mb-3 border-l-4 border-green-500 pl-2">题库分类目录</h3>
      <ul class="space-y-1">
        <li
          @click="$emit('select-tag', '全部')"
          class="flex justify-between items-center text-sm cursor-pointer p-2 rounded transition-colors border border-transparent"
          :class="selectedTag === '全部' ? 'bg-green-50 text-green-700 font-bold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
        >
          <span>全部高频真题</span>
          <span class="text-gray-500 font-mono">{{ masterBank.length }} 题</span>
        </li>
        <li
          v-for="(count, topic) in popularTags" :key="topic"
          @click="$emit('select-tag', topic)"
          class="flex justify-between items-center text-sm cursor-pointer p-2 rounded transition-colors border border-transparent group"
          :class="selectedTag === topic ? 'bg-green-50 text-green-700 font-bold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
        >
          <span class="break-all mr-2 group-hover:text-green-600 transition-colors">{{ topic }}</span>
          <span class="text-gray-400 font-mono whitespace-nowrap group-hover:text-green-500">{{ count }} 题</span>
        </li>
        <li v-if="!popularTags || Object.keys(popularTags).length === 0" class="text-gray-400 text-sm p-2">暂无数据</li>
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

<template>
  <div class="lg:col-span-1 bg-white rounded-xl shadow-sm border border-gray-100 h-fit lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto custom-scrollbar">

    <!-- Learning Progress -->
    <div class="p-4 lg:p-5 border-b border-gray-100">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-gray-800 flex items-center gap-1.5">
          <svg class="w-4 h-4 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
          学习进度
        </h3>
        <span class="text-xs text-gray-400">{{ practiceStats.practiced_questions || 0 }}/{{ practiceStats.total_questions || 0 }} 题</span>
      </div>

      <!-- Overall progress bar -->
      <div class="w-full bg-gray-100 rounded-full h-2 mb-4 overflow-hidden">
        <div
          class="h-2 rounded-full transition-all duration-500"
          :class="progressPercent >= 80 ? 'bg-green-500' : progressPercent >= 40 ? 'bg-amber-400' : 'bg-indigo-500'"
          :style="{ width: progressPercent + '%' }"
        ></div>
      </div>

      <!-- Per-difficulty breakdown -->
      <div class="space-y-2.5">
        <div v-for="diff in diffOrder" :key="diff" class="group">
          <div class="flex items-center justify-between text-xs mb-1">
            <span class="font-medium" :class="diffColor(diff)">{{ diff }}</span>
            <span class="text-gray-400">
              {{ (practiceStats.by_difficulty?.[diff]?.practiced || 0) }}/{{ (practiceStats.by_difficulty?.[diff]?.total || 0) }}
              <span v-if="practiceStats.by_difficulty?.[diff]?.avg_score" class="ml-1" :class="scoreColor(practiceStats.by_difficulty[diff].avg_score)">
                {{ practiceStats.by_difficulty[diff].avg_score }}分
              </span>
            </span>
          </div>
          <div class="w-full bg-gray-100 rounded-full h-1.5 overflow-hidden">
            <div
              class="h-1.5 rounded-full transition-all duration-500"
              :class="diffBarColor(diff)"
              :style="{ width: diffProgress(diff) + '%' }"
            ></div>
          </div>
        </div>
      </div>

      <!-- Average score badge -->
      <div v-if="practiceStats.avg_score" class="mt-3 flex items-center gap-2 text-xs">
        <span class="text-gray-500">平均最高分</span>
        <span class="font-bold px-2 py-0.5 rounded-full" :class="scoreBadgeClass(practiceStats.avg_score)">
          {{ practiceStats.avg_score }}
        </span>
      </div>
    </div>

    <!-- Daily Recommendation -->
    <div class="p-4 lg:p-5 border-b border-gray-100">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-gray-800 flex items-center gap-1.5">
          <svg class="w-4 h-4 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
          每日推荐
        </h3>
        <button @click="$emit('refresh-recommend')" class="text-xs text-gray-400 hover:text-indigo-500 transition" title="换一批">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
        </button>
      </div>
      <div v-if="recommendations.length === 0" class="text-xs text-gray-400 text-center py-4">
        暂无推荐，继续加油
      </div>
      <ul v-else class="space-y-1.5">
        <li
          v-for="q in recommendations"
          :key="q.id"
          @click="$emit('go-to-question', q)"
          class="group flex items-start gap-2 p-2 rounded-lg cursor-pointer hover:bg-indigo-50 transition"
        >
          <span class="flex-shrink-0 mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded" :class="freqBadgeClass(q.frequency)">
            {{ q.frequency > 1 ? '高频' : '新题' }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-xs text-gray-700 leading-relaxed line-clamp-2 group-hover:text-indigo-700 transition">{{ q.question }}</p>
            <div class="flex items-center gap-1.5 mt-1">
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{{ shortCat(q.cat1) }}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded" :class="diffChipClass(q.difficulty)">{{ shortDiff(q.difficulty) }}</span>
            </div>
          </div>
        </li>
      </ul>
    </div>

    <!-- Starred Quick Access -->
    <div class="p-4 lg:p-5 border-b border-gray-100">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-gray-800 flex items-center gap-1.5">
          <svg class="w-4 h-4 text-yellow-500" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
          收藏夹
        </h3>
        <span class="text-xs text-gray-400">{{ starredItems.length }} 题</span>
      </div>
      <div v-if="starredItems.length === 0" class="text-xs text-gray-400 text-center py-4">
        点击题目卡片的 <svg class="inline w-3 h-3 text-gray-300" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg> 收藏
      </div>
      <ul v-else class="space-y-1 max-h-40 overflow-y-auto custom-scrollbar-inner">
        <li
          v-for="q in starredItems"
          :key="q.id"
          @click="$emit('go-to-question', q)"
          class="flex items-center gap-2 p-1.5 rounded cursor-pointer hover:bg-yellow-50 transition text-xs text-gray-600 hover:text-yellow-700"
        >
          <svg class="w-3 h-3 text-yellow-400 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
          <span class="truncate">{{ q.question }}</span>
        </li>
      </ul>
    </div>

    <!-- Compact Pie Chart -->
    <div class="p-4 lg:p-5 border-b border-gray-100">
      <h3 class="text-sm font-bold text-gray-800 mb-2 flex items-center gap-1.5">
        <svg class="w-4 h-4 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" /></svg>
        考点分布
      </h3>
      <div v-show="masterBank.length > 0" ref="chartRef" class="w-full h-[200px]"></div>
      <div v-if="masterBank.length === 0" class="w-full h-[120px] flex items-center justify-center text-gray-400 text-xs">暂无数据</div>
    </div>

    <!-- Category Directory -->
    <div class="p-4 lg:p-5 border-b border-gray-100">
      <h3 class="text-sm font-bold text-gray-800 mb-2 flex items-center gap-1.5">
        <svg class="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" /></svg>
        分类目录
      </h3>
      <ul class="space-y-0.5">
        <li
          @click="$emit('select-tag', '全部')"
          class="flex justify-between items-center text-xs cursor-pointer px-2 py-1.5 rounded-lg transition-colors border border-transparent"
          :class="selectedTag === '全部' ? 'bg-green-50 text-green-700 font-semibold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
        >
          <span>全部</span>
          <span class="text-gray-400 font-mono text-[11px]">{{ masterBank.length }}</span>
        </li>
        <li
          v-for="(count, topic) in popularTags" :key="topic"
          @click="$emit('select-tag', topic)"
          class="flex justify-between items-center text-xs cursor-pointer px-2 py-1.5 rounded-lg transition-colors border border-transparent group"
          :class="selectedTag === topic ? 'bg-green-50 text-green-700 font-semibold border-green-200' : 'hover:bg-gray-50 text-gray-600'"
        >
          <span class="break-all mr-2 group-hover:text-green-600 transition-colors">{{ topic }}</span>
          <span class="text-gray-400 font-mono text-[11px] whitespace-nowrap group-hover:text-green-500">{{ count }}</span>
        </li>
      </ul>
    </div>

    <!-- Hot Tech Stacks -->
    <div class="p-4 lg:p-5">
      <h3 class="text-sm font-bold text-gray-800 mb-2 flex items-center gap-1.5">
        <svg class="w-4 h-4 text-rose-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" /></svg>
        热门技术栈
      </h3>
      <ul class="space-y-1">
        <li v-for="(count, tech) in analytics.tech_trends" :key="tech" class="flex justify-between items-center text-xs px-2 py-1 rounded hover:bg-gray-50">
          <span class="text-gray-700 break-all mr-2">{{ tech }}</span>
          <span class="text-gray-400 font-mono text-[11px] whitespace-nowrap bg-gray-100 px-1.5 py-0.5 rounded">{{ count }}</span>
        </li>
        <li v-if="!analytics.tech_trends || Object.keys(analytics.tech_trends).length === 0" class="text-gray-400 text-xs px-2">暂无数据</li>
      </ul>
    </div>

    <!-- Refresh button (compact) -->
    <div class="px-4 lg:px-5 pb-4 lg:pb-5">
      <button @click="$emit('refresh')" class="w-full bg-gray-50 text-gray-500 px-3 py-1.5 rounded-lg hover:bg-gray-100 hover:text-gray-700 transition text-xs font-medium border border-gray-200">
        刷新数据
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  analytics: { type: Object, default: () => ({ tech_trends: {} }) },
  masterBank: { type: Array, default: () => [] },
  popularTags: { type: Object, default: () => ({}) },
  selectedTag: { type: String, default: '全部' },
  practiceStats: { type: Object, default: () => ({}) },
  recommendSeed: { type: Number, default: 0 }
})

defineEmits(['refresh', 'select-tag', 'go-to-question', 'refresh-recommend'])

const chartRef = ref(null)
let myChart = null
let resizeHandler = null

// ── Learning progress helpers ──
const diffOrder = ['L1-基础', 'L2-中等', 'L3-困难']

const progressPercent = computed(() => {
  const s = props.practiceStats
  if (!s.total_questions) return 0
  return Math.round((s.practiced_questions / s.total_questions) * 100)
})

const diffProgress = (diff) => {
  const d = props.practiceStats.by_difficulty?.[diff]
  if (!d || !d.total) return 0
  return Math.round((d.practiced / d.total) * 100)
}

const diffColor = (diff) => {
  if (diff.includes('L1')) return 'text-green-600'
  if (diff.includes('L2')) return 'text-amber-600'
  if (diff.includes('L3')) return 'text-red-600'
  return 'text-gray-600'
}

const diffBarColor = (diff) => {
  if (diff.includes('L1')) return 'bg-green-400'
  if (diff.includes('L2')) return 'bg-amber-400'
  if (diff.includes('L3')) return 'bg-red-400'
  return 'bg-gray-400'
}

const scoreColor = (score) => {
  if (score >= 80) return 'text-green-600'
  if (score >= 60) return 'text-amber-600'
  return 'text-red-600'
}

const scoreBadgeClass = (score) => {
  if (score >= 80) return 'bg-green-100 text-green-700'
  if (score >= 60) return 'bg-amber-100 text-amber-700'
  return 'bg-red-100 text-red-700'
}

// ── Daily recommendation logic ──
const recommendations = computed(() => {
  // Trigger recomputation when seed changes
  void props.recommendSeed

  const practicedIds = new Set()
  if (props.practiceStats.by_difficulty) {
    // We don't have individual practiced IDs in the stats, so we use a heuristic:
    // prioritize by frequency and difficulty diversity
  }

  const pool = [...props.masterBank]

  // Sort by: unpracticed first (we'll pick from various difficulty levels)
  // Then by frequency descending
  pool.sort((a, b) => (b.frequency || 1) - (a.frequency || 1))

  // Pick diverse recommendations: 1 easy, 2 medium, 1 hard (if available)
  const picks = []
  const byDiff = { 'L1': [], 'L2': [], 'L3': [] }
  pool.forEach(q => {
    const d = (q.difficulty || '').substring(0, 2)
    if (byDiff[d]) byDiff[d].push(q)
    else byDiff['L2'].push(q) // default to medium
  })

  // Random-ish selection using a seed for variety
  const seed = props.recommendSeed || Date.now()
  const pickFrom = (arr, count) => {
    if (arr.length === 0) return []
    const result = []
    const used = new Set()
    for (let i = 0; i < count && i < arr.length; i++) {
      let idx = (seed * (i + 1) * 7 + i * 13) % arr.length
      let tries = 0
      while (used.has(idx) && tries < arr.length) {
        idx = (idx + 1) % arr.length
        tries++
      }
      if (!used.has(idx)) {
        used.add(idx)
        result.push(arr[idx])
      }
    }
    return result
  }

  picks.push(...pickFrom(byDiff['L1'], 1))
  picks.push(...pickFrom(byDiff['L2'], 2))
  picks.push(...pickFrom(byDiff['L3'], 1))

  // If we don't have enough, fill from remaining
  if (picks.length < 4) {
    const remaining = pool.filter(q => !picks.includes(q))
    picks.push(...pickFrom(remaining, 4 - picks.length))
  }

  return picks.slice(0, 5)
})

// ── Starred items ──
const starredItems = computed(() => {
  return props.masterBank.filter(q => q.is_starred).slice(0, 20)
})

// ── Helper formatters ──
const shortCat = (cat) => {
  if (!cat) return '未分类'
  // "A.项目经验与设计" -> "项目经验"
  const match = cat.match(/^[A-F]\.(.+)/)
  if (match) {
    const name = match[1]
    // Take first meaningful part
    const parts = name.split(/[与和、]/)
    return parts[0].substring(0, 4)
  }
  return cat.substring(0, 4)
}

const shortDiff = (diff) => {
  if (!diff) return '?'
  if (diff.includes('L1')) return '基础'
  if (diff.includes('L2')) return '中等'
  if (diff.includes('L3')) return '困难'
  return diff
}

const diffChipClass = (diff) => {
  if (!diff) return 'bg-gray-100 text-gray-500'
  if (diff.includes('L1')) return 'bg-green-100 text-green-600'
  if (diff.includes('L2')) return 'bg-amber-100 text-amber-600'
  if (diff.includes('L3')) return 'bg-red-100 text-red-600'
  return 'bg-gray-100 text-gray-500'
}

const freqBadgeClass = (freq) => {
  if (freq >= 3) return 'bg-red-100 text-red-600'
  if (freq >= 2) return 'bg-orange-100 text-orange-600'
  return 'bg-gray-100 text-gray-500'
}

// ── Pie chart ──
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
      textStyle: { color: '#374151', fontSize: 12 },
      formatter: '{b}: {c} 题 ({d}%)'
    },
    series: [{
      type: 'pie',
      radius: ['30%', '65%'],
      center: ['50%', '55%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
      label: { show: true, fontSize: 10, formatter: '{b}\n{d}%' },
      labelLine: { show: true, length: 6, length2: 10 },
      data: pieData
    }]
  }, true)
}

watch(() => props.masterBank, () => nextTick(() => {
  if (myChart) myChart.resize()
  updateDistributionChart()
}), { deep: true })

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

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background-color: #cbd5e1; border-radius: 20px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background-color: #94a3b8; }
.custom-scrollbar-inner::-webkit-scrollbar { width: 4px; }
.custom-scrollbar-inner::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar-inner::-webkit-scrollbar-thumb { background-color: #e2e8f0; border-radius: 20px; }
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>

<template>
  <div class="lg:col-span-1 bg-white dark:bg-surface-800 rounded-2xl shadow-card dark:shadow-glass-dark border border-surface-200/80 dark:border-ink-700/50 h-fit lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto custom-scrollbar">

    <!-- Collapse toggle -->
    <button
      @click="$emit('toggle-collapse')"
      class="w-full flex items-center justify-center p-2 text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-50 dark:hover:bg-surface-700 transition-colors border-b border-surface-200/80 dark:border-ink-700/60"
      title="收起侧边栏"
    >
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
      </svg>
    </button>

    <!-- Learning Progress -->
    <div class="p-5 border-b border-surface-200/80 dark:border-ink-700/60">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 flex items-center gap-2">
          <div class="w-6 h-6 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center">
            <svg class="w-3.5 h-3.5 text-primary-600 dark:text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
          </div>
          学习进度
        </h3>
        <span class="text-xs text-ink-400 dark:text-ink-500 tabular-nums">{{ practiceStats.practiced_questions || 0 }}/{{ practiceStats.total_questions || 0 }} 题</span>
      </div>

      <!-- Overall progress bar -->
      <div class="w-full bg-surface-200 dark:bg-ink-700 rounded-full h-2 mb-4 overflow-hidden">
        <div
          class="h-2 rounded-full transition-all duration-700 ease-out"
          :class="progressPercent >= 80 ? 'bg-gradient-to-r from-emerald-400 to-emerald-500' : progressPercent >= 40 ? 'bg-gradient-to-r from-amber-400 to-amber-500' : 'bg-gradient-to-r from-primary-400 to-primary-500'"
          :style="{ width: progressPercent + '%' }"
        ></div>
      </div>

      <!-- Per-difficulty breakdown -->
      <div class="space-y-3">
        <div v-for="diff in diffOrder" :key="diff" class="group">
          <div class="flex items-center justify-between text-xs mb-1.5">
            <span class="font-semibold" :class="diffColor(diff)">{{ diff }}</span>
            <span class="text-ink-400 dark:text-ink-500 tabular-nums">
              {{ (practiceStats.by_difficulty?.[diff]?.practiced || 0) }}/{{ (practiceStats.by_difficulty?.[diff]?.total || 0) }}
              <span v-if="practiceStats.by_difficulty?.[diff]?.avg_score" class="ml-1 font-bold" :class="scoreColor(practiceStats.by_difficulty[diff].avg_score)">
                {{ practiceStats.by_difficulty[diff].avg_score }}分
              </span>
            </span>
          </div>
          <div class="w-full bg-surface-200 dark:bg-ink-700 rounded-full h-1.5 overflow-hidden">
            <div
              class="h-1.5 rounded-full transition-all duration-700 ease-out"
              :class="diffBarColor(diff)"
              :style="{ width: diffProgress(diff) + '%' }"
            ></div>
          </div>
        </div>
      </div>

      <!-- Average score badge -->
      <div v-if="practiceStats.avg_score" class="mt-4 flex items-center gap-2 text-xs">
        <span class="text-ink-400 dark:text-ink-500">平均最高分</span>
        <span class="font-bold px-2.5 py-0.5 rounded-lg" :class="scoreBadgeClass(practiceStats.avg_score)">
          {{ practiceStats.avg_score }}
        </span>
      </div>
    </div>

    <!-- Daily Recommendation -->
    <div class="p-5 border-b border-surface-200/80 dark:border-ink-700/60">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 flex items-center gap-2">
          <div class="w-6 h-6 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
            <svg class="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
          </div>
          每日推荐
        </h3>
        <button @click="$emit('refresh-recommend')" class="text-xs text-ink-400 hover:text-primary-500 dark:hover:text-primary-400 transition p-1 rounded-lg hover:bg-primary-50 dark:hover:bg-primary-900/30" title="换一批">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
        </button>
      </div>
      <div v-if="recommendations.length === 0" class="text-xs text-ink-400 dark:text-ink-500 text-center py-6">
        暂无推荐，继续加油
      </div>
      <ul v-auto-animate class="space-y-1.5">
        <li
          v-for="q in recommendations"
          :key="q.id"
          @click="$emit('go-to-question', q)"
          class="group flex items-start gap-2.5 p-2.5 rounded-xl cursor-pointer hover:bg-primary-50/60 dark:hover:bg-primary-900/20 transition-all duration-200"
        >
          <span class="flex-shrink-0 mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded-md" :class="freqBadgeClass(q.frequency)">
            {{ q.frequency > 1 ? '高频' : '新题' }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-xs text-ink-600 dark:text-ink-400 leading-relaxed line-clamp-2 group-hover:text-primary-700 dark:group-hover:text-primary-400 transition-colors">{{ q.question }}</p>
            <div class="flex items-center gap-1.5 mt-1.5">
              <span class="text-[10px] px-1.5 py-0.5 rounded-md bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400">{{ shortCat(q.cat1) }}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded-md" :class="diffChipClass(q.difficulty)">{{ shortDiff(q.difficulty) }}</span>
            </div>
          </div>
        </li>
      </ul>
    </div>

    <!-- Starred Quick Access -->
    <div class="p-5 border-b border-surface-200/80 dark:border-ink-700/60">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 flex items-center gap-2">
          <div class="w-6 h-6 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
            <svg class="w-3.5 h-3.5 text-amber-500 dark:text-amber-400" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
          </div>
          收藏夹
        </h3>
        <span class="text-xs text-ink-400 dark:text-ink-500 tabular-nums">{{ starredItems.length }} 题</span>
      </div>
      <div v-if="starredItems.length === 0" class="text-xs text-ink-400 dark:text-ink-500 text-center py-6">
        点击题目卡片的 <svg class="inline w-3 h-3 text-ink-300 dark:text-ink-600" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg> 收藏
      </div>
      <ul v-auto-animate v-else class="space-y-0.5 max-h-40 overflow-y-auto custom-scrollbar">
        <li
          v-for="q in starredItems"
          :key="q.id"
          @click="$emit('go-to-question', q)"
          class="flex items-center gap-2 p-2 rounded-lg cursor-pointer hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-all duration-200 text-xs text-ink-600 dark:text-ink-400 hover:text-amber-700 dark:hover:text-amber-400"
        >
          <svg class="w-3 h-3 text-amber-400 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
          <span class="truncate">{{ q.question }}</span>
        </li>
      </ul>
    </div>

    <!-- Compact Pie Chart -->
    <div class="p-5 border-b border-surface-200/80 dark:border-ink-700/60">
      <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 mb-3 flex items-center gap-2">
        <div class="w-6 h-6 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center">
          <svg class="w-3.5 h-3.5 text-violet-600 dark:text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" /></svg>
        </div>
        考点分布
      </h3>
      <div v-show="masterBank.length > 0" ref="chartRef" class="w-full h-[200px]"></div>
      <div v-if="masterBank.length === 0" class="w-full h-[120px] flex items-center justify-center text-ink-400 dark:text-ink-500 text-xs">暂无数据</div>
    </div>

    <!-- Category Directory -->
    <div class="p-5 border-b border-surface-200/80 dark:border-ink-700/60">
      <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 mb-3 flex items-center gap-2">
        <div class="w-6 h-6 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
          <svg class="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" /></svg>
        </div>
        分类目录
      </h3>
      <ul v-auto-animate class="space-y-0.5">
        <li
          @click="$emit('select-tag', '全部')"
          class="flex justify-between items-center text-xs cursor-pointer px-2.5 py-2 rounded-lg transition-all duration-200 border border-transparent"
          :class="selectedTag === '全部' ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-semibold border-emerald-200 dark:border-emerald-800' : 'hover:bg-surface-50 dark:hover:bg-ink-800 text-ink-600 dark:text-ink-400'"
        >
          <span>全部</span>
          <span class="text-ink-400 dark:text-ink-500 font-mono text-[11px] tabular-nums">{{ masterBank.length }}</span>
        </li>
        <li
          v-for="(count, topic) in popularTags" :key="topic"
          @click="$emit('select-tag', topic)"
          class="flex justify-between items-center text-xs cursor-pointer px-2.5 py-2 rounded-lg transition-all duration-200 border border-transparent group"
          :class="selectedTag === topic ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-semibold border-emerald-200 dark:border-emerald-800' : 'hover:bg-surface-50 dark:hover:bg-ink-800 text-ink-600 dark:text-ink-400'"
        >
          <span class="break-all mr-2 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-colors">{{ topic }}</span>
          <span class="text-ink-400 dark:text-ink-500 font-mono text-[11px] whitespace-nowrap tabular-nums group-hover:text-emerald-500 dark:group-hover:text-emerald-400">{{ count }}</span>
        </li>
      </ul>
    </div>

    <!-- Hot Tech Stacks -->
    <div class="p-5 border-b border-surface-200/80 dark:border-ink-700/60">
      <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 mb-3 flex items-center gap-2">
        <div class="w-6 h-6 rounded-lg bg-rose-100 dark:bg-rose-900/30 flex items-center justify-center">
          <svg class="w-3.5 h-3.5 text-rose-600 dark:text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" /></svg>
        </div>
        热门技术栈
      </h3>
      <ul class="space-y-1">
        <li v-for="(count, tech) in analytics.tech_trends" :key="tech" class="flex justify-between items-center text-xs px-2.5 py-1.5 rounded-lg hover:bg-surface-50 dark:hover:bg-ink-800 transition-colors">
          <span class="text-ink-600 dark:text-ink-400 break-all mr-2">{{ tech }}</span>
          <span class="text-ink-400 dark:text-ink-500 font-mono text-[11px] whitespace-nowrap bg-surface-200 dark:bg-ink-700 px-2 py-0.5 rounded-md tabular-nums">{{ count }}</span>
        </li>
        <li v-if="!analytics.tech_trends || Object.keys(analytics.tech_trends).length === 0" class="text-ink-400 dark:text-ink-500 text-xs px-2.5 py-2">暂无数据</li>
      </ul>
    </div>

    <!-- Refresh button -->
    <div class="px-5 pb-5 pt-3">
      <button @click="$emit('refresh')" class="w-full btn-secondary text-xs py-2">
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
        刷新数据
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([PieChart, TooltipComponent, CanvasRenderer])
import { useTheme } from '../composables/useTheme.js'

const { isDark } = useTheme()

const props = defineProps({
  analytics: { type: Object, default: () => ({ tech_trends: {} }) },
  masterBank: { type: Array, default: () => [] },
  popularTags: { type: Object, default: () => ({}) },
  selectedTag: { type: String, default: '全部' },
  practiceStats: { type: Object, default: () => ({}) },
  recommendSeed: { type: Number, default: 0 }
})

defineEmits(['refresh', 'select-tag', 'go-to-question', 'refresh-recommend', 'toggle-collapse'])

const chartRef = ref(null)
let myChart = null
let resizeHandler = null

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
  if (diff.includes('L1')) return 'text-emerald-600 dark:text-emerald-400'
  if (diff.includes('L2')) return 'text-amber-600 dark:text-amber-400'
  if (diff.includes('L3')) return 'text-red-600 dark:text-red-400'
  return 'text-ink-600 dark:text-ink-400'
}

const diffBarColor = (diff) => {
  if (diff.includes('L1')) return 'bg-gradient-to-r from-emerald-400 to-emerald-500'
  if (diff.includes('L2')) return 'bg-gradient-to-r from-amber-400 to-amber-500'
  if (diff.includes('L3')) return 'bg-gradient-to-r from-red-400 to-red-500'
  return 'bg-ink-400'
}

const scoreColor = (score) => {
  if (score >= 80) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 60) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

const scoreBadgeClass = (score) => {
  if (score >= 80) return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
  if (score >= 60) return 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
  return 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
}

const recommendations = computed(() => {
  void props.recommendSeed
  const pool = [...props.masterBank]
  pool.sort((a, b) => (b.frequency || 1) - (a.frequency || 1))

  const picks = []
  const byDiff = { 'L1': [], 'L2': [], 'L3': [] }
  pool.forEach(q => {
    const d = (q.difficulty || '').substring(0, 2)
    if (byDiff[d]) byDiff[d].push(q)
    else byDiff['L2'].push(q)
  })

  const seed = props.recommendSeed || Date.now()
  const pickFrom = (arr, count) => {
    if (arr.length === 0) return []
    const result = []
    const used = new Set()
    for (let i = 0; i < count && i < arr.length; i++) {
      let idx = (seed * (i + 1) * 7 + i * 13) % arr.length
      let tries = 0
      while (used.has(idx) && tries < arr.length) { idx = (idx + 1) % arr.length; tries++ }
      if (!used.has(idx)) { used.add(idx); result.push(arr[idx]) }
    }
    return result
  }

  picks.push(...pickFrom(byDiff['L1'], 1))
  picks.push(...pickFrom(byDiff['L2'], 2))
  picks.push(...pickFrom(byDiff['L3'], 1))
  if (picks.length < 4) {
    const remaining = pool.filter(q => !picks.includes(q))
    picks.push(...pickFrom(remaining, 4 - picks.length))
  }
  return picks.slice(0, 5)
})

const starredItems = computed(() => props.masterBank.filter(q => q.is_starred).slice(0, 20))

const shortCat = (cat) => {
  if (!cat) return '未分类'
  const match = cat.match(/^[A-F]\.(.+)/)
  if (match) { const parts = match[1].split(/[与和、]/); return parts[0].substring(0, 4) }
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
  if (!diff) return 'bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400'
  if (diff.includes('L1')) return 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
  if (diff.includes('L2')) return 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400'
  if (diff.includes('L3')) return 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400'
  return 'bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400'
}

const freqBadgeClass = (freq) => {
  if (freq >= 3) return 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'
  if (freq >= 2) return 'bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400'
  return 'bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400'
}

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
  if (myChart) myChart.resize()
  updateDistributionChart()
}), { deep: true })

watch(isDark, () => {
  if (myChart) updateDistributionChart()
})

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
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>

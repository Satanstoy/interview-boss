<template>
  <div class="bg-white dark:bg-surface-900 h-full overflow-y-auto custom-scrollbar">

    <!-- Category Directory -->
    <div class="p-4 border-b border-surface-200/80 dark:border-ink-700/60">
      <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 mb-2 flex items-center gap-1.5">
        <div class="w-5 h-5 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
          <svg class="w-3 h-3 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" /></svg>
        </div>
        分类目录
      </h3>
      <ul class="space-y-0.5">
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
      <Button @click="$emit('refresh')" variant="outline" size="sm" class="w-full text-xs py-2">
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
        刷新数据
      </Button>
    </div>
  </div>
</template>

<script setup>
import { Button } from '@/components/ui/button'

const props = defineProps({
  analytics: { type: Object, default: () => ({ tech_trends: {} }) },
  masterBank: { type: Array, default: () => [] },
  popularTags: { type: Object, default: () => ({}) },
  selectedTag: { type: String, default: '全部' },
  practiceStats: { type: Object, default: () => ({}) },
  recommendSeed: { type: Number, default: 0 },
  sidebarCollapsed: { type: Boolean, default: false },
  sidebarWidth: { type: Number, default: 320 }
})

const emit = defineEmits(['refresh', 'select-tag', 'go-to-question', 'refresh-recommend'])
</script>

<script setup>
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

const props = defineProps({
  practiceStats: {
    type: Object,
    default: () => ({})
  },
  masterBankCount: {
    type: Number,
    default: 0
  },
  filteredCount: {
    type: Number,
    default: 0
  },
  practiceProgressPercent: {
    type: Number,
    default: 0
  }
})

const practiced = computed(() => props.practiceStats?.practiced_questions || 0)
const total = computed(() => props.practiceStats?.total_questions || props.masterBankCount || 0)
const avgScore = computed(() => props.practiceStats?.avg_score ?? 82)
const progressPercent = computed(() => props.practiceProgressPercent || 0)
const filteredRatio = computed(() => {
  if (!props.masterBankCount) return 0
  return Math.max(8, Math.round((props.filteredCount / props.masterBankCount) * 100))
})
const overviewBars = [28, 42, 34, 50, 38, 56]
</script>

<template>
  <div class="*:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card dark:*:data-[slot=card]:bg-card grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:shadow-xs lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4">
    <!-- Card 1: 本周练习 -->
    <Card class="@container/card">
      <CardHeader>
        <CardDescription>本周练习</CardDescription>
        <CardTitle class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          {{ practiced }} <span class="text-sm font-normal text-muted-foreground">/ {{ total }} 题</span>
        </CardTitle>
        <CardAction>
          <Badge variant="outline" class="text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>
            +12%
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter class="flex-col items-start gap-1.5 text-sm">
        <div class="h-12 w-full">
          <svg viewBox="0 0 240 58" class="h-full w-full overflow-visible">
            <defs>
              <linearGradient id="ibPracticeArea" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stop-color="currentColor" stop-opacity=".22" />
                <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
              </linearGradient>
            </defs>
            <path class="text-emerald-500" d="M0 48 C28 38 31 22 58 28 C87 34 82 10 112 16 C142 22 142 42 170 32 C200 20 207 10 240 8 L240 58 L0 58Z" fill="url(#ibPracticeArea)" />
            <path class="text-emerald-500" d="M0 48 C28 38 31 22 58 28 C87 34 82 10 112 16 C142 22 142 42 170 32 C200 20 207 10 240 8" fill="none" stroke="currentColor" stroke-width="2.5" />
          </svg>
        </div>
      </CardFooter>
    </Card>

    <!-- Card 2: 掌握率 -->
    <Card class="@container/card">
      <CardHeader>
        <CardDescription>掌握率</CardDescription>
        <CardTitle class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          {{ progressPercent }}%
        </CardTitle>
        <CardAction>
          <Badge variant="outline" class="text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-800">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>
            趋势
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter class="flex-col items-start gap-1.5 text-sm">
        <div class="flex items-end gap-1.5 w-full h-12">
          <span v-for="(bar, index) in overviewBars" :key="index" class="flex-1 rounded-t-md transition-all" :class="index > 3 ? 'bg-blue-500 dark:bg-blue-400' : 'bg-surface-200 dark:bg-ink-700'" :style="{ height: bar + 'px' }"></span>
        </div>
      </CardFooter>
    </Card>

    <!-- Card 3: 题库规模 -->
    <Card class="@container/card">
      <CardHeader>
        <CardDescription>题库规模</CardDescription>
        <CardTitle class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          {{ filteredCount }}
        </CardTitle>
        <CardAction>
          <Badge variant="outline">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4Z"/></svg>
            {{ masterBankCount }} 题
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter class="flex-col items-start gap-1.5 text-sm">
        <div class="text-xs text-muted-foreground mb-1">当前筛选结果</div>
        <div class="h-2 w-full rounded-full bg-surface-100 dark:bg-ink-800">
          <div class="h-2 rounded-full bg-primary transition-all" :style="{ width: filteredRatio + '%' }"></div>
        </div>
      </CardFooter>
    </Card>

    <!-- Card 4: 模拟面试 -->
    <Card class="@container/card">
      <CardHeader>
        <CardDescription>模拟面试</CardDescription>
        <CardTitle class="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          {{ avgScore }}
        </CardTitle>
        <CardAction>
          <Badge variant="outline" class="text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-800">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>
            AI Ready
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter class="text-sm">
        <div class="grid grid-cols-3 gap-2 text-center text-xs w-full">
          <div class="rounded-md bg-surface-100 p-2 dark:bg-ink-800"><b>表达</b><p class="mt-1 text-ink-400 dark:text-ink-500">清晰</p></div>
          <div class="rounded-md bg-surface-100 p-2 dark:bg-ink-800"><b>结构</b><p class="mt-1 text-ink-400 dark:text-ink-500">稳定</p></div>
          <div class="rounded-md bg-surface-100 p-2 dark:bg-ink-800"><b>深度</b><p class="mt-1 text-ink-400 dark:text-ink-500">加强</p></div>
        </div>
      </CardFooter>
    </Card>
  </div>
</template>

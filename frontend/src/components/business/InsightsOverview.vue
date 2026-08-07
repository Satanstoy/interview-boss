<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, CircleAlert } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import AppLoading from '@/components/common/AppLoading.vue'
import PracticeHeatmap from './PracticeHeatmap.vue'
import PracticeStreakCard from './PracticeStreakCard.vue'
import PracticeTrendChart from './PracticeTrendChart.vue'
import PracticeDifficultyChart from './PracticeDifficultyChart.vue'
import PracticeRadarChart from './PracticeRadarChart.vue'
import PracticeRecentTimeline from './PracticeRecentTimeline.vue'
import PracticeQuadChart from './PracticeQuadChart.vue'

const props = defineProps({
  snapshot: { type: Object, required: true },
  practiceActivity: { type: Object, default: null },
  practiceLoading: { type: Boolean, default: false },
})

const router = useRouter()
const route = useRoute()
const summary = computed(() => props.snapshot?.summary || {})

const statCards = [
  { key: 'jd_count', label: '岗位 JD', suffix: '份' },
  { key: 'interview_count', label: '面经题目', suffix: '条' },
  { key: 'question_count', label: '题库覆盖', suffix: '题' },
  { key: 'practiced_question_count', label: '已练题目', suffix: '题' },
]

const todayCount = computed(() => {
  const heatmap = props.practiceActivity?.heatmap || []
  return heatmap[heatmap.length - 1]?.count || 0
})

function goReadiness() {
  router.push({ name: 'insights-readiness', query: { ...route.query } })
}

function goPractice() {
  router.push({ name: 'practice', query: { ...route.query } })
}
</script>

<template>
  <section class="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-5 md:px-6 md:py-7">
    <header class="flex flex-col gap-1">
      <p class="text-sm text-muted-foreground">目标岗位：{{ snapshot.target_position.name }}</p>
      <h1 class="text-2xl font-semibold tracking-tight text-foreground">洞察总览</h1>
      <p class="max-w-2xl text-sm text-muted-foreground">把岗位、题库和个人练习证据整理成下一步准备任务。</p>
    </header>

    <div v-if="summary.evidence_state === 'insufficient'" class="flex items-start gap-3 rounded-xl border border-amber-300/60 bg-amber-50/70 p-4 text-amber-950 dark:border-amber-800/60 dark:bg-amber-950/20 dark:text-amber-100">
      <CircleAlert class="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p class="text-sm font-medium">尚未形成个人能力分数</p>
        <p class="mt-1 text-xs opacity-80">当前洞察只使用岗位、题库和已有记录，不会把题库频次当成掌握度。</p>
      </div>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Card v-for="card in statCards" :key="card.key">
        <CardContent class="p-4">
          <p class="text-xs text-muted-foreground">{{ card.label }}</p>
          <p class="mt-2 text-2xl font-semibold text-foreground">{{ summary[card.key] }}<span class="ml-1 text-sm font-normal text-muted-foreground">{{ card.suffix }}</span></p>
        </CardContent>
      </Card>
    </div>

    <Card data-testid="quadrant-card">
      <CardHeader>
        <CardTitle>岗位重点知识</CardTitle>
        <p class="text-sm text-muted-foreground">横轴是你的熟练度，纵轴是岗位热度 —— 右上角是要守住的优势，左上角是要优先补的重点。</p>
      </CardHeader>
      <CardContent>
        <PracticeQuadChart :items="snapshot.readiness.items" />
      </CardContent>
    </Card>

    <section v-if="practiceLoading" class="rounded-xl border border-border bg-card p-6 shadow-sm">
      <AppLoading type="skeleton" rows="4" />
    </section>

    <section v-else-if="!practiceActivity" class="rounded-xl border border-border bg-card p-6 shadow-sm">
      <div class="flex flex-col items-center gap-3 py-10 text-center">
        <p class="text-sm font-medium text-foreground">练习足迹暂不可用</p>
        <p class="max-w-md text-xs text-muted-foreground">刷新页面或稍后再试，开始刷题后这里会展示你的打卡热力图和进步趋势。</p>
      </div>
    </section>

    <section v-else class="flex flex-col gap-3">
      <div class="flex items-center justify-between gap-4">
        <div>
          <h2 class="text-lg font-semibold tracking-tight text-foreground">我的练习足迹</h2>
          <p class="mt-0.5 text-sm text-muted-foreground">坚持每天刷题，图表会见证你的成长。</p>
        </div>
        <Button variant="outline" size="sm" @click="goPractice">去刷题 <ArrowRight class="h-4 w-4" /></Button>
      </div>
      <div class="grid gap-3 xl:grid-cols-3">
        <div class="xl:col-span-2">
          <PracticeHeatmap :data="practiceActivity.heatmap || []" />
        </div>
        <PracticeStreakCard
          :streak="practiceActivity.streak || { current: 0, longest: 0 }"
          :today-count="todayCount"
        />
        <div class="xl:col-span-2">
          <PracticeTrendChart :data="practiceActivity.trend || []" />
        </div>
        <PracticeDifficultyChart :data="practiceActivity.difficulty || []" />
        <PracticeRadarChart :data="practiceActivity.radar || []" />
        <div class="xl:col-span-2">
          <PracticeRecentTimeline :data="practiceActivity.recent || []" />
        </div>
      </div>
    </section>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between gap-4">
        <div>
          <CardTitle>本周最该做</CardTitle>
          <p class="mt-1 text-sm text-muted-foreground">优先处理岗位热度高、个人证据不足的主题。</p>
        </div>
        <Button variant="outline" size="sm" @click="goReadiness">查看准备度 <ArrowRight class="h-4 w-4" /></Button>
      </CardHeader>
      <CardContent>
        <div v-if="snapshot.actions.length" class="grid gap-3 lg:grid-cols-3">
          <div v-for="item in snapshot.actions" :key="item.id" class="rounded-xl border border-border bg-muted/20 p-4">
            <div class="flex items-start justify-between gap-3">
              <h2 class="font-medium text-foreground">{{ item.title }}</h2>
              <Badge :variant="item.priority === 'high' ? 'destructive' : 'secondary'">{{ item.priority === 'high' ? '优先' : '可巩固' }}</Badge>
            </div>
            <p class="mt-2 min-h-10 text-sm leading-6 text-muted-foreground">{{ item.description }}</p>
            <Button variant="link" class="mt-2 h-auto px-0" @click="goPractice">{{ item.action }} <ArrowRight class="h-4 w-4" /></Button>
          </div>
        </div>
        <p v-else class="py-6 text-center text-sm text-muted-foreground">题库还没有形成可执行的主题建议。</p>
      </CardContent>
    </Card>
  </section>
</template>

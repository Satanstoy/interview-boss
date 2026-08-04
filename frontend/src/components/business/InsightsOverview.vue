<script setup>
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, CircleAlert } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const props = defineProps({
  snapshot: { type: Object, required: true },
})

const router = useRouter()
const route = useRoute()
const summary = props.snapshot.summary

const statCards = [
  { key: 'jd_count', label: '岗位 JD', suffix: '份' },
  { key: 'interview_count', label: '面经题目', suffix: '条' },
  { key: 'question_count', label: '题库覆盖', suffix: '题' },
  { key: 'practiced_question_count', label: '已练题目', suffix: '题' },
]

function goReadiness() {
  router.push({ name: 'insights-readiness', query: { ...route.query } })
}

function goPractice() {
  router.push({ name: 'mock-interview', query: { ...route.query } })
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

<script setup>
import { computed, ref } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import PracticeDualRadarChart from './PracticeDualRadarChart.vue'

const props = defineProps({ snapshot: { type: Object, required: true } })

const statusLabel = {
  not_started: '未开始',
  needs_work: '需要加强',
  developing: '进行中',
  stable: '稳定',
  evidence_only: '待补评分',
}

function statusVariant(status) {
  if (status === 'needs_work') return 'destructive'
  if (status === 'stable') return 'default'
  return 'secondary'
}

// 雷达只画热度 Top 8，其余主题用紧凑列表补充，不丢信息
const topTopics = computed(() => {
  const items = props.snapshot.readiness.items || []
  const ranked = [...items].sort((a, b) => (b.question_frequency || 0) - (a.question_frequency || 0))
  return { top: ranked.slice(0, 8), rest: ranked.slice(8) }
})

const matrixOpen = ref(false)
</script>

<template>
  <section class="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-5 md:px-6 md:py-7">
    <header class="flex flex-col gap-1">
      <p class="text-sm text-muted-foreground">目标岗位：{{ props.snapshot.target_position.name }}</p>
      <h1 class="text-2xl font-semibold tracking-tight text-foreground">岗位准备度</h1>
      <p class="mt-1 max-w-2xl text-sm text-muted-foreground">岗位要什么（热度）× 你掌握什么（熟练度）—— 空当越大越该补。</p>
    </header>

    <div v-if="!props.snapshot.data_quality.has_practice_evidence" class="rounded-xl border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
      当前没有结构化练习评分，雷达只有岗位热度线，熟练度线会在刷题复习后出现。
    </div>

    <Card data-testid="dual-radar-card">
      <CardHeader>
        <CardTitle>能力差距</CardTitle>
        <p class="text-sm text-muted-foreground">只画热度 Top 8 主题；其余主题在下方列表补充。</p>
      </CardHeader>
      <CardContent>
        <PracticeDualRadarChart :items="props.snapshot.readiness.items" />
      </CardContent>
    </Card>

    <Card v-if="topTopics.rest.length" data-testid="rest-topics">
      <CardHeader>
        <CardTitle>其余主题</CardTitle>
        <p class="text-sm text-muted-foreground">雷达只画热度 Top 8，其余 {{ topTopics.rest.length }} 个主题不丢。</p>
      </CardHeader>
      <CardContent>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="item in topTopics.rest"
            :key="item.id"
            class="rounded-full border border-border bg-muted/30 px-3 py-1 text-xs text-muted-foreground"
          >
            {{ item.name }} · <span class="font-semibold text-foreground">{{ item.question_frequency }}</span>
          </span>
        </div>
      </CardContent>
    </Card>

    <Card data-testid="matrix-card">
      <CardHeader>
        <CardTitle>能力矩阵</CardTitle>
        <p class="text-sm text-muted-foreground">共覆盖 {{ props.snapshot.summary.question_count }} 道题，按题库二级主题聚合。</p>
        <Button
          variant="outline"
          size="sm"
          class="mt-2"
          @click="matrixOpen = !matrixOpen"
        >
          {{ matrixOpen ? '收起能力矩阵' : '展开能力矩阵' }}
        </Button>
      </CardHeader>
      <CardContent v-if="matrixOpen" class="p-0">
        <div v-if="props.snapshot.readiness.items.length" class="overflow-x-auto">
          <table class="w-full min-w-[720px] text-left text-sm">
            <thead class="border-y border-border bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th class="px-5 py-3 font-medium">主题</th>
                <th class="px-4 py-3 font-medium">题目</th>
                <th class="px-4 py-3 font-medium">岗位热度</th>
                <th class="px-4 py-3 font-medium">练习次数</th>
                <th class="px-4 py-3 font-medium">平均分</th>
                <th class="px-4 py-3 font-medium">熟练度</th>
                <th class="px-4 py-3 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in props.snapshot.readiness.items" :key="item.id" class="border-b border-border last:border-0">
                <td class="px-5 py-4">
                  <p class="font-medium text-foreground">{{ item.name }}</p>
                  <p class="mt-1 text-xs text-muted-foreground">{{ item.reason }}</p>
                </td>
                <td class="px-4 py-4 text-muted-foreground">{{ item.question_count }}</td>
                <td class="px-4 py-4 text-muted-foreground">{{ item.question_frequency }}</td>
                <td class="px-4 py-4 text-muted-foreground">{{ item.practice_count }}</td>
                <td class="px-4 py-4 font-medium text-foreground">{{ item.average_score == null ? '—' : item.average_score }}</td>
                <td class="px-4 py-4 font-medium text-foreground">{{ item.proficiency == null ? '—' : item.proficiency + '%' }}</td>
                <td class="px-4 py-4"><Badge :variant="statusVariant(item.status)">{{ statusLabel[item.status] || item.status }}</Badge></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="px-5 py-8 text-center text-sm text-muted-foreground">暂无岗位准备数据。</p>
      </CardContent>
    </Card>
  </section>
</template>

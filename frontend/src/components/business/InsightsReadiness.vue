<script setup>
import { computed, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Network } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const KnowledgeGraph = defineAsyncComponent({
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/KnowledgeGraph.vue'),
})

const props = defineProps({ snapshot: { type: Object, required: true } })
const route = useRoute()
const router = useRouter()
const isGraphView = computed(() => route.query.view === 'graph')

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

function openGraph() {
  router.push({ name: 'insights-readiness', query: { ...route.query, view: 'graph' } })
}

function closeGraph() {
  router.push({ name: 'insights-readiness', query: { preview: route.query.preview } })
}
</script>

<template>
  <section class="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-5 md:px-6 md:py-7">
    <header class="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
      <div>
        <p class="text-sm text-muted-foreground">目标岗位：{{ props.snapshot.target_position.name }}</p>
        <h1 class="text-2xl font-semibold tracking-tight text-foreground">岗位准备度</h1>
        <p class="mt-1 max-w-2xl text-sm text-muted-foreground">先看岗位能力覆盖和个人证据，再决定下一轮训练。</p>
      </div>
      <Button v-if="!isGraphView" variant="outline" @click="openGraph"><Network class="h-4 w-4" /> 打开知识图谱</Button>
      <Button v-else variant="outline" @click="closeGraph">返回能力矩阵</Button>
    </header>

    <template v-if="isGraphView">
      <Card>
        <CardHeader>
          <CardTitle>知识图谱</CardTitle>
          <p class="text-sm text-muted-foreground">用于探索主题关联；具体准备优先级以能力矩阵为准。</p>
        </CardHeader>
        <CardContent><KnowledgeGraph /></CardContent>
      </Card>
    </template>

    <template v-else>
      <div v-if="!props.snapshot.data_quality.has_practice_evidence" class="rounded-xl border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
        当前没有结构化练习评分，表格中的“准备状态”只代表个人练习记录，不代表通过概率。
      </div>

      <Card>
        <CardHeader>
          <CardTitle>能力矩阵</CardTitle>
          <p class="text-sm text-muted-foreground">共覆盖 {{ props.snapshot.summary.question_count }} 道题，按题库二级主题聚合。</p>
        </CardHeader>
        <CardContent class="p-0">
          <div v-if="props.snapshot.readiness.items.length" class="overflow-x-auto">
            <table class="w-full min-w-[720px] text-left text-sm">
              <thead class="border-y border-border bg-muted/30 text-xs text-muted-foreground">
                <tr>
                  <th class="px-5 py-3 font-medium">主题</th>
                  <th class="px-4 py-3 font-medium">题目</th>
                  <th class="px-4 py-3 font-medium">岗位热度</th>
                  <th class="px-4 py-3 font-medium">练习次数</th>
                  <th class="px-4 py-3 font-medium">平均分</th>
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
                  <td class="px-4 py-4"><Badge :variant="statusVariant(item.status)">{{ statusLabel[item.status] || item.status }}</Badge></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="px-5 py-8 text-center text-sm text-muted-foreground">暂无岗位准备数据。</p>
        </CardContent>
      </Card>
    </template>
  </section>
</template>

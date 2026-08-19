<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, CheckCircle2, Clock3, FlaskConical, XCircle } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { fetchEvaluationOverview, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { evaluationTargetLabel, formatDate, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvalProgressBar from '@/components/business/EvalProgressBar.vue'
import { Badge } from '@/components/ui/badge'

const router = useRouter()
const overview = ref(null)
const loading = ref(true)
const error = ref('')
const humanReviews = computed(() => overview.value?.human_reviews || { total: 0, comparison_groups: [] })
const runs = ref([])
const byTarget = computed(() => overview.value?.by_target || [])
const byTargetSort = computed(() => [...byTarget.value].sort((a, b) => (b.failed_count / Math.max(b.run_count, 1)) - (a.failed_count / Math.max(a.run_count, 1))))
const failedRuns = computed(() => runs.value.filter(r => r.quality_status === 'failed' || r.status === 'failed').slice(0, 6))
function passRate(item) {
  if (!item.run_count) return 0
  return Math.round((item.passed_count / item.run_count) * 100)
}

const cards = computed(() => [
  { label: '已完成', value: overview.value?.counts?.completed || 0, icon: CheckCircle2, tone: 'text-emerald-600' },
  { label: '正在执行', hint: '队列中或 E2E 运行中', value: (overview.value?.counts?.running || 0) + (overview.value?.counts?.queued || 0), icon: Activity, tone: 'text-amber-600' },
  { label: '等待启动', hint: '已经创建，等待 Worker', value: overview.value?.counts?.created || 0, icon: Clock3, tone: 'text-muted-foreground' },
  { label: '失败或取消', hint: '需要进一步查看原因', value: (overview.value?.counts?.failed || 0) + (overview.value?.counts?.cancelled || 0), icon: XCircle, tone: 'text-destructive' },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [overviewData, runData] = await Promise.all([fetchEvaluationOverview(), fetchEvaluationRuns()])
    overview.value = overviewData
    runs.value = runData.runs || []
  } catch (err) {
    error.value = err.message || '评测总览加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div aria-labelledby="eval-overview-title" class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader
        title="测评可视化"
        description="站在五步评测流程之上，快速查看系统状态、人工证据和下一步需要处理的事项。"
        :show-flow="false"
      >
        <template #actions>
          <Button variant="outline" @click="router.push('/admin/evals/experiments')">
            <FlaskConical class="mr-1.5 size-4" /> 开始一次完整评测
          </Button>
        </template>
      </EvaluationPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
        {{ error }}
        <Button class="ml-3" size="sm" variant="outline" @click="load">重试</Button>
      </div>
      <template v-else>
        <div class="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <AppCard v-for="card in cards" :key="card.label" class="min-h-28">
            <div class="flex items-start justify-between">
              <div><div class="text-sm text-muted-foreground">{{ card.label }}</div><div class="mt-2 text-3xl font-semibold">{{ card.value }}</div><div class="mt-1 text-xs text-muted-foreground">{{ card.hint || '累计运行数量' }}</div></div>
              <component :is="card.icon" :class="['size-5', card.tone]" />
            </div>
          </AppCard>
        </div>

        <!-- 质量健康看板：按目标通过率排名 -->
        <AppCard v-if="byTarget.length" class="mt-6" title="质量健康看板" description="各评测目标的通过率与最近分数，按失败率降序排列。">
          <div aria-live="polite" class="space-y-3">
            <div v-for="item in byTargetSort" :key="item.target_type" class="rounded-lg border border-border/60 p-3">
              <div class="flex items-center justify-between gap-3">
                <div class="min-w-0">
                  <span class="font-medium">{{ evaluationTargetLabel(item.target_type) }}</span>
                  <span class="ml-2 text-xs text-muted-foreground">{{ item.run_count }} 次运行</span>
                  <span class="ml-2 rounded-full bg-destructive/10 px-2 py-0.5 text-xs text-destructive">{{ item.failed_count }} 失败</span>
                </div>
                <div class="shrink-0 w-36">
                  <div class="h-1.5 overflow-hidden rounded-full bg-muted">
                    <EvalProgressBar :value="passRate(item)" variant="success" size="sm" />
                  </div>
                  <div class="mt-0.5 text-right text-xs text-muted-foreground">{{ passRate(item) }}% 通过</div>
                </div>
              </div>
            </div>
          </div>
        </AppCard>

        <!-- 待处理的失败 Run -->
        <AppCard v-if="failedRuns.length" class="mt-6" title="待处理的失败评测" description="这些评测需要管理员查看原因并决定重跑或接受。">
          <div class="divide-y divide-border/60">
            <Button v-for="run in failedRuns" :key="run.id" variant="ghost" size="sm" class="flex w-full items-center gap-3 p-3 text-left hover:bg-muted/40" @click="router.push(`/admin/evals/runs/${run.id}`)">
              <span class="font-medium">评测 #{{ run.id }}</span>
              <Badge variant="default">{{ statusLabel(run.status) }}</Badge>
              <span v-if="run.target_type" class="text-xs text-muted-foreground">{{ evaluationTargetLabel(run.target_type) }}</span>
              <span class="ml-auto text-xs text-muted-foreground">{{ formatDate(run.created_at) }}</span>
            </Button>
          </div>
        </AppCard>

        <AppCard class="mt-6" title="人工 A/B 汇总" description="人工判断是独立质量证据，用来核验版本差异，不覆盖 Hard Gate 或 Judge。">
          <div class="mb-4 flex items-center justify-between rounded-lg bg-muted/30 px-4 py-3">
            <span class="text-sm text-muted-foreground">已完成人工比较</span>
            <span class="text-2xl font-semibold">{{ humanReviews.total }}</span>
          </div>
          <div v-if="!humanReviews.comparison_groups.length" class="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-8 text-center text-sm text-muted-foreground">
            还没有人工 A/B 数据。完成两条同一 comparison group 的 E2E Run 后，可以进入人工 A/B 核验。
          </div>
          <div v-else class="divide-y divide-border/60">
            <div v-for="group in humanReviews.comparison_groups" :key="`${group.comparison_group}-${group.run_a_id}-${group.run_b_id}`" class="flex flex-wrap items-center gap-3 py-4">
              <div class="min-w-48 flex-1">
                <div class="font-medium">{{ group.comparison_group }}</div>
                <div class="mt-1 text-xs text-muted-foreground">{{ group.run_a_target_release_key }} 对比 {{ group.run_b_target_release_key }}</div>
              </div>
              <div class="flex flex-wrap gap-2 text-xs">
                <span class="rounded-full bg-emerald-500/10 px-2 py-1 text-emerald-700">A 胜 {{ group.a_wins }}</span>
                <span class="rounded-full bg-blue-500/10 px-2 py-1 text-blue-700">B 胜 {{ group.b_wins }}</span>
                <span class="rounded-full bg-muted px-2 py-1 text-muted-foreground">平局 {{ group.ties }}</span>
                <span class="rounded-full bg-destructive/10 px-2 py-1 text-destructive">都失败 {{ group.both_fail }}</span>
              </div>
              <Button size="sm" variant="ghost" @click="router.push({ path: '/admin/evals/reviews', query: { group: group.comparison_group } })">进入人工 A/B</Button>
            </div>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, RefreshCw } from '@lucide/vue'
import { useRouter } from 'vue-router'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { fetchEvaluationOverview, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { evaluationTargetLabel, formatDate, qualityStatusLabel, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvalScoreBar from '@/components/business/EvalScoreBar.vue'
import EvalProgressBar from '@/components/business/EvalProgressBar.vue'

const router = useRouter()
const overview = ref(null)
const runs = ref([])
const loading = ref(true)
const error = ref('')
const statusFilter = ref('all')
const targetFilter = ref('__all__')

const byTarget = computed(() => overview.value?.by_target || [])

// 质量优先排序：failed/pending 在前，再按时间倒序
const sortedRuns = computed(() => {
  const priority = (run) => {
    if (run.quality_status === 'failed') return 0
    if (run.quality_status === 'pending' || run.quality_status === 'not_evaluated') return 1
    if (['running', 'queued', 'created'].includes(run.status)) return 2
    return 3
  }
  return [...runs.value].sort((a, b) => {
    const p = priority(a) - priority(b)
    if (p !== 0) return p
    return new Date(b.created_at) - new Date(a.created_at)
  })
})

const filteredRuns = computed(() => {
  return sortedRuns.value.filter(run => {
    if (statusFilter.value === 'all') {
      // no-op
    } else if (statusFilter.value === 'completed') {
      if (run.status !== 'completed') return false
    } else if (statusFilter.value === 'failed') {
      if (!['failed', 'cancelled'].includes(run.status) && run.quality_status !== 'failed') return false
    } else if (statusFilter.value === 'running') {
      if (!['running', 'queued', 'created'].includes(run.status)) return false
    }
    if (targetFilter.value !== '__all__' && run.target_type !== targetFilter.value) return false
    return true
  })
})

const targetOptions = computed(() => {
  const set = new Set()
  runs.value.forEach(run => { if (run.target_type) set.add(run.target_type) })
  return ['__all__', ...set]
})

const byTargetSort = computed(() => {
  return [...byTarget.value].sort((a, b) => {
    const ra = a.failed_count / Math.max(a.run_count, 1)
    const rb = b.failed_count / Math.max(b.run_count, 1)
    return rb - ra
  })
})

function passRate(item) {
  if (!item.run_count) return 0
  return Math.round((item.passed_count / item.run_count) * 100)
}

function qualityBadgeClass(q) {
  if (q === 'passed') return 'text-emerald-600 bg-emerald-500/10'
  if (q === 'failed') return 'text-destructive bg-destructive/10'
  return 'text-muted-foreground bg-muted'
}

const cards = computed(() => [
  { label: '已完成', value: overview.value?.counts?.completed || 0 },
  { label: '正在执行', value: (overview.value?.counts?.running || 0) + (overview.value?.counts?.queued || 0) },
  { label: '等待启动', value: overview.value?.counts?.created || 0 },
  { label: '失败或取消', value: (overview.value?.counts?.failed || 0) + (overview.value?.counts?.cancelled || 0) },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [summary, runData] = await Promise.all([fetchEvaluationOverview(), fetchEvaluationRuns()])
    overview.value = summary
    runs.value = runData.runs || []
  } catch (err) {
    error.value = err.message || '评测结果加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div aria-labelledby="eval-results-title" class="h-full overflow-y-auto custom-scrollbar custom-scrollbar-always">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader
        title="评测结果"
        description="查看每次完整 E2E 的实时进度、逐 Case 结果和最终聚合状态。"
        active-key="results"
      >
        <template #actions>
          <Button variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新结果</Button>
        </template>
      </EvaluationPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
        {{ error }}
        <Button class="ml-3" size="sm" variant="outline" @click="load">重试</Button>
      </div>
      <template v-else>
        <!-- 顶部统计卡 -->
        <div class="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <AppCard v-for="card in cards" :key="card.label" class="min-h-24">
            <div class="text-sm text-muted-foreground">{{ card.label }}</div>
            <div class="mt-2 text-3xl font-semibold">{{ card.value }}</div>
          </AppCard>
        </div>

        <!-- 各目标质量分布 -->
        <AppCard v-if="byTarget.length" class="mt-6" title="各目标质量分布" description="按评测目标聚合运行质量，一眼看出哪个目标最需要关注。">
          <div class="space-y-3">
            <div v-for="item in byTargetSort" :key="item.target_type" class="rounded-lg border border-border/60 p-3">
              <div class="flex items-center justify-between gap-3">
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="font-medium">{{ evaluationTargetLabel(item.target_type) }}</span>
                    <span class="truncate text-xs text-muted-foreground">{{ item.target_release_key }}</span>
                  </div>
                  <div class="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span>{{ item.run_count }} 次运行</span>
                    <span class="text-emerald-600">{{ item.passed_count }} 通过</span>
                    <span class="text-destructive">{{ item.failed_count }} 失败</span>
                  </div>
                </div>
                <div class="shrink-0 w-40">
                  <div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>通过率</span><span>{{ passRate(item) }}%</span></div>
                  <div class="h-1.5 overflow-hidden rounded-full bg-muted">
                    <EvalProgressBar :value="passRate(item)" variant="success" size="sm" />
                  </div>
                  <div v-if="item.avg_score != null" class="mt-1 text-right font-mono text-xs text-muted-foreground">均分 {{ item.avg_score.toFixed(3) }}</div>
                </div>
              </div>
            </div>
          </div>
        </AppCard>

        <!-- Run 列表：筛选 + 分数横条 + 质量排序 -->
        <AppCard class="mt-6" title="最近评测运行" description="默认失败/未通过优先；点击一条查看完整 E2E 详情。">
          <div class="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-2">
            <span class="text-xs text-muted-foreground">状态：</span>
            <Button v-for="f in [{ key: 'all', label: '全部' }, { key: 'completed', label: '完成' }, { key: 'failed', label: '失败/异常' }, { key: 'running', label: '进行中' }]" :key="f.key" variant="ghost" size="sm" :class="['rounded-md px-2 py-1 text-xs transition-colors', statusFilter === f.key ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:text-foreground']" @click="statusFilter = f.key">{{ f.label }}</Button>
            <span class="ml-2 text-xs text-muted-foreground">目标：</span>
            <Button v-for="target in targetOptions" :key="target" variant="ghost" size="sm" :class="['rounded-md px-2 py-1 text-xs transition-colors', targetFilter === target ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:text-foreground']" @click="targetFilter = target">{{ target === '__all__' ? '全部目标' : evaluationTargetLabel(target) }}</Button>
          </div>
          <div v-if="!filteredRuns.length" class="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-10 text-center">
            <div class="font-medium">还没有评测记录</div>
            <p class="mt-1 text-sm text-muted-foreground">先在“测评实验”中选择一个被测版本，创建一场完整 E2E 评测。</p>
            <Button class="mt-4" size="sm" @click="router.push('/admin/evals/experiments')">开始一次完整评测</Button>
          </div>
          <div aria-live="polite" v-else class="divide-y divide-border/60">
            <Button
              v-for="run in filteredRuns"
              :key="run.id"
              variant="ghost" size="sm"
              class="flex w-full flex-col gap-3 p-4 text-left transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-4"
              @click="router.push(`/admin/evals/runs/${run.id}`)"
            >
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-medium">评测 #{{ run.id }}</span>
                  <span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span>
                  <span class="text-[11px] text-muted-foreground">质量</span>
                  <span :class="['rounded-full px-2 py-0.5 text-xs', qualityBadgeClass(run.quality_status)]">{{ qualityStatusLabel(run.quality_status) }}</span>
                  <span v-if="run.target_type" class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{{ evaluationTargetLabel(run.target_type) }}</span>
                  <span v-if="run.comparison_group" class="rounded-full bg-blue-500/10 px-2 py-0.5 text-xs text-blue-700">对比组 {{ run.comparison_group }}</span>
                </div>
                <div class="mt-1 text-xs text-muted-foreground">{{ formatDate(run.created_at) }} · 被测：{{ run.target_release_key || '未命名' }}</div>
              </div>
              <div class="w-full sm:w-48 shrink-0 space-y-1">
                <EvalScoreBar :deterministic="run.score?.deterministic_mean" :judge="run.score?.judge_mean" :final="run.score?.final_mean" />
                <div class="flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span>{{ runProgress(run) }}%</span></div>
              </div>
            </Button>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>
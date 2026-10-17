<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, RefreshCw } from '@lucide/vue'
import { useRouter } from 'vue-router'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { fetchEvaluationCapabilities, fetchEvaluationOverview, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import {
  buildByTargetSort,
  evaluationTargetLabel,
  formatDate,
  qualityStatusLabel,
  runDistribution,
  statusClass,
  statusLabel,
} from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvalMetricCards from '@/components/business/EvalMetricCards.vue'
import EvalOutcomeDistribution from '@/components/business/EvalOutcomeDistribution.vue'

const router = useRouter()
const overview = ref(null)
const runs = ref([])
const capabilities = ref([])
const loading = ref(true)
const error = ref('')
const selectedTarget = ref('__all__')
const outcomeFilter = ref('all')

const byTarget = computed(() => overview.value?.by_target || [])
const targetSummaries = computed(() => buildByTargetSort(byTarget.value))
const targetOptions = computed(() => ['__all__', ...targetSummaries.value.map(item => item.target_type)])

const selectedTargetSummary = computed(() => (
  selectedTarget.value === '__all__'
    ? null
    : targetSummaries.value.find(item => item.target_type === selectedTarget.value) || null
))

const selectedDistribution = computed(() => (
  selectedTargetSummary.value ? runDistribution(selectedTargetSummary.value) : null
))

const selectedRuns = computed(() => runs.value
  .filter(run => selectedTarget.value === '__all__' || run.target_type === selectedTarget.value)
  .sort((a, b) => {
    const order = { failed: 0, pending: 1, completed: 2, queued: 3, running: 3, created: 3 }
    return (order[a.quality_status] ?? 4) - (order[b.quality_status] ?? 4) || new Date(b.created_at || 0) - new Date(a.created_at || 0)
  }))

function metricCardsForTarget(target) {
  if (target?.metric_cards?.length) return target.metric_cards
  return runs.value.find(run => run.target_type === target?.target_type && run.metric_cards?.length)?.metric_cards || []
}

const metricCards = computed(() => selectedTargetSummary.value ? metricCardsForTarget(selectedTargetSummary.value) : [])

const evaluationScope = computed(() => {
  const targetType = selectedTarget.value === '__all__' ? null : selectedTarget.value
  const capability = targetType ? capabilities.value.find(item => item.target_type === targetType) : null
  const latestRun = targetType
    ? runs.value
      .filter(run => run.target_type === targetType)
      .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))[0]
    : null
  const evaluationRelease = capability?.evaluation_release || {}
  const harness = capability?.project_harness || {}
  const evaluationKey = latestRun?.benchmark_suite_release_key || latestRun?.evaluation_release_key
    || (latestRun ? '历史数据未记录' : evaluationRelease.release_key || '—')
  const harnessKey = latestRun
    ? (latestRun.project_harness_key && latestRun.project_harness_version
        ? `${latestRun.project_harness_key}@${latestRun.project_harness_version}`
        : '历史数据未记录')
    : (harness.harness_key && harness.version
        ? `${harness.harness_key}@${harness.version}`
        : evaluationRelease.project_harness_release_key || '—')
  return {
    target: targetType ? evaluationTargetLabel(targetType) : '多个评测目标',
    harness: harnessKey,
    evaluation: evaluationKey,
    caseCount: targetType ? (capability?.case_count || selectedDistribution.value?.total || 0) : '—',
  }
})

const attentionCases = computed(() => {
  const cases = selectedRuns.value.flatMap(run => (
    run.attention_cases?.length
      ? run.attention_cases.map(item => ({ ...item, run }))
      : fallbackAttentionCases(run)
  ))
  return outcomeFilter.value === 'all' ? cases : cases.filter(item => item.outcome === outcomeFilter.value)
})

const attentionBuckets = computed(() => [
  { key: 'failed', label: '失败 Case', items: attentionCases.value.filter(item => item.outcome === 'failed'), tone: 'text-destructive' },
  { key: 'poor', label: '表现不佳', items: attentionCases.value.filter(item => item.outcome === 'poor'), tone: 'text-amber-700' },
  { key: 'pending', label: '未完成 / 处理中', items: attentionCases.value.filter(item => item.outcome === 'pending'), tone: 'text-muted-foreground' },
])

const summaryCards = computed(() => selectedDistribution.value ? [
  { label: '失败 Case', value: selectedDistribution.value.failed, tone: 'text-destructive' },
  { label: '表现不佳', value: selectedDistribution.value.poor, tone: 'text-amber-700' },
  { label: '未完成 / 处理中', value: selectedDistribution.value.pending, tone: 'text-muted-foreground' },
  { label: '通过 Case', value: selectedDistribution.value.passed, tone: 'text-emerald-700' },
] : [])

function fallbackAttentionCases(run) {
  const distribution = runDistribution(run)
  return ['failed', 'poor', 'pending'].flatMap(outcome => {
    const count = distribution[outcome]
    if (!count) return []
    return [{
      run_id: run.id,
      item_id: 0,
      target_type: run.target_type,
      case_key: `评测 #${run.id}`,
      score: run.score?.final_mean ?? null,
      outcome,
      primary_failure_reason: outcome === 'failed' ? '执行或硬性要求未通过' : outcome === 'poor' ? '综合表现低于目标线' : '评测尚未完成',
      count,
      run,
    }]
  })
}

function chooseTarget(target) {
  selectedTarget.value = target
  outcomeFilter.value = 'all'
}

function selectOutcome(outcome) {
  outcomeFilter.value = outcome === 'passed' ? 'all' : outcome
}

function openRun(item) {
  if (item.run_id) router.push(`/admin/evals/runs/${item.run_id}`)
}

function qualityBadgeClass(value) {
  if (value === 'passed') return 'text-emerald-700 bg-emerald-500/10'
  if (value === 'failed') return 'text-destructive bg-destructive/10'
  return 'text-muted-foreground bg-muted'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [summary, runData, capabilityData] = await Promise.all([
      fetchEvaluationOverview(),
      fetchEvaluationRuns(),
      fetchEvaluationCapabilities(),
    ])
    overview.value = summary
    runs.value = runData.runs || []
    capabilities.value = capabilityData.targets || []
    if (selectedTarget.value === '__all__' && targetSummaries.value.length) {
      selectedTarget.value = targetSummaries.value[0].target_type
    }
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
      >
        <template #actions>
          <Button variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新结果</Button>
          <Button @click="router.push('/admin/evals/experiments')">开始一次评测</Button>
        </template>
      </EvaluationPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
        {{ error }}
        <Button class="ml-3" size="sm" variant="outline" @click="load">重试</Button>
      </div>

      <template v-else>
        <AppCard class="mt-6" title="本次评测范围" description="结果和可视化都基于这组固定版本。">
          <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div class="rounded-lg bg-muted/40 p-3">
              <div class="text-xs text-muted-foreground">评测对象</div>
              <div class="mt-1 truncate font-medium" :title="evaluationScope.target">{{ evaluationScope.target }}</div>
            </div>
            <div class="rounded-lg bg-muted/40 p-3">
              <div class="text-xs text-muted-foreground">Harness 版本</div>
              <div class="mt-1 truncate font-mono text-sm font-medium" :title="evaluationScope.harness">{{ evaluationScope.harness }}</div>
            </div>
            <div class="rounded-lg bg-muted/40 p-3">
              <div class="text-xs text-muted-foreground">评测集版本</div>
              <div class="mt-1 truncate font-mono text-sm font-medium" :title="evaluationScope.evaluation">{{ evaluationScope.evaluation }}</div>
            </div>
            <div class="rounded-lg bg-muted/40 p-3">
              <div class="text-xs text-muted-foreground">Case 数</div>
              <div class="mt-1 font-medium">{{ evaluationScope.caseCount }}</div>
            </div>
          </div>
        </AppCard>

        <section aria-label="评测结果摘要" class="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <button
            v-for="card in summaryCards"
            :key="card.label"
            type="button"
            class="rounded-xl border border-border/70 bg-card p-4 text-left transition-colors hover:bg-muted/30"
            @click="outcomeFilter = card.label === '失败 Case' ? 'failed' : card.label === '表现不佳' ? 'poor' : card.label.startsWith('未完成') ? 'pending' : 'all'"
          >
            <div class="text-sm text-muted-foreground">{{ card.label }}</div>
            <div :class="['mt-1 text-3xl font-semibold', card.tone]">{{ card.value }}</div>
          </button>
        </section>

        <AppCard class="mt-6" title="评测目标" description="不同目标使用各自的评测标准，不跨目标合并质量分数。">
          <div class="flex flex-wrap gap-2" role="tablist" aria-label="评测目标">
            <button
              v-for="target in targetOptions"
              :key="target"
              type="button"
              role="tab"
              :aria-selected="selectedTarget === target"
              :class="[
                'rounded-lg border px-3 py-2 text-sm transition-colors',
                selectedTarget === target ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border/70 text-muted-foreground hover:bg-muted/40',
              ]"
              @click="chooseTarget(target)"
            >
              {{ target === '__all__' ? '全部目标' : evaluationTargetLabel(target) }}
            </button>
          </div>
          <div v-if="selectedTarget === '__all__'" class="mt-5 grid gap-3 lg:grid-cols-2">
            <article v-for="target in targetSummaries" :key="target.target_type" class="rounded-xl border border-border/60 bg-muted/10 p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 class="font-medium">{{ evaluationTargetLabel(target.target_type) }}</h3>
                  <div class="mt-1 text-xs text-muted-foreground">{{ runDistribution(target).total }} 个 Case · {{ (runs.filter(run => run.target_type === target.target_type)).length }} 次运行</div>
                </div>
                <div class="text-sm text-muted-foreground">失败 {{ runDistribution(target).failed }} · 不佳 {{ runDistribution(target).poor }} · 通过 {{ runDistribution(target).passed }}</div>
              </div>
              <div class="mt-4"><EvalOutcomeDistribution :distribution="runDistribution(target)" :aria-label="`${evaluationTargetLabel(target.target_type)} 结果分布`" @select="selectOutcome" /></div>
              <div v-if="metricCardsForTarget(target).length" class="mt-5 border-t border-border/60 pt-4">
                <div class="mb-2 text-xs font-semibold text-muted-foreground">核心指标</div>
                <EvalMetricCards :metrics="metricCardsForTarget(target)" />
              </div>
            </article>
          </div>
          <div v-else class="mt-5 rounded-xl border border-border/60 bg-muted/10 p-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div class="font-medium">{{ evaluationTargetLabel(selectedTarget) }}</div>
                <div class="mt-1 text-xs text-muted-foreground">{{ selectedDistribution.total }} 个 Case · {{ selectedRuns.length }} 次运行</div>
              </div>
              <div class="text-sm text-muted-foreground">失败 {{ selectedDistribution.failed }} · 不佳 {{ selectedDistribution.poor }} · 通过 {{ selectedDistribution.passed }}</div>
            </div>
            <div class="mt-4"><EvalOutcomeDistribution :distribution="selectedDistribution" aria-label="当前目标评测结果分布" @select="selectOutcome" /></div>
            <div v-if="metricCards.length" class="mt-5 border-t border-border/60 pt-4">
              <div class="mb-2 text-xs font-semibold text-muted-foreground">核心指标</div>
              <EvalMetricCards :metrics="metricCards" />
            </div>
          </div>
        </AppCard>

        <AppCard class="mt-6" title="需要关注的 Case" description="失败和表现不佳优先；通过的 Case 不占用首屏。">
          <div class="flex flex-wrap gap-2 border-b border-border/60 pb-3">
            <Button v-for="filter in [{ key: 'all', label: '全部' }, { key: 'failed', label: '失败' }, { key: 'poor', label: '表现不佳' }, { key: 'pending', label: '未完成' } ]" :key="filter.key" variant="ghost" size="sm" :aria-pressed="outcomeFilter === filter.key" :class="outcomeFilter === filter.key ? 'bg-primary/10 text-primary' : 'text-muted-foreground'" @click="outcomeFilter = filter.key">{{ filter.label }}</Button>
          </div>
          <div v-for="bucket in attentionBuckets" :key="bucket.key" class="border-b border-border/60 py-4 last:border-b-0">
            <div class="mb-2 flex items-center justify-between gap-2">
              <h3 :class="['text-sm font-medium', bucket.tone]">{{ bucket.label }}</h3>
              <span class="text-xs text-muted-foreground">{{ bucket.items.length }} 条</span>
            </div>
            <div v-if="!bucket.items.length" class="rounded-lg bg-muted/30 px-3 py-4 text-sm text-muted-foreground">暂无</div>
            <button v-for="item in bucket.items" :key="`${item.run_id}-${item.item_id}-${item.outcome}`" type="button" class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-muted/40" @click="openRun(item)">
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium">{{ item.case_key }}</span>
              <span class="mt-0.5 block truncate text-xs text-muted-foreground">评测 #{{ item.run_id }} · {{ item.primary_failure_reason }}</span>
              </span>
              <span v-if="item.count" class="text-xs text-muted-foreground">{{ item.count }} 个</span>
              <span v-if="item.score != null" class="font-mono text-xs">{{ Number(item.score).toFixed(3) }}</span>
              <ArrowRight class="size-4 shrink-0 text-muted-foreground" />
            </button>
          </div>
        </AppCard>

        <AppCard class="mt-6" title="最近评测" description="点击评测查看完整执行记录和 Case 证据。">
          <div v-if="!selectedRuns.length" class="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-10 text-center text-sm text-muted-foreground">还没有评测运行。</div>
          <div v-else class="divide-y divide-border/60">
            <button v-for="run in selectedRuns" :key="run.id" type="button" class="flex w-full flex-col gap-3 p-4 text-left transition-colors hover:bg-muted/40 sm:flex-row sm:items-center" @click="router.push(`/admin/evals/runs/${run.id}`)">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-medium">评测 #{{ run.id }}</span>
                  <Badge :class="statusClass(run.status)">{{ statusLabel(run.status) }}</Badge>
                  <Badge :class="qualityBadgeClass(run.quality_status)">{{ qualityStatusLabel(run.quality_status) }}</Badge>
                  <span class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{{ evaluationTargetLabel(run.target_type) }}</span>
                </div>
                <div class="mt-1 text-xs text-muted-foreground">{{ formatDate(run.created_at) }} · {{ run.target_release_key || '未命名版本' }}</div>
              </div>
              <div class="w-full shrink-0 sm:w-64">
                <EvalOutcomeDistribution :distribution="runDistribution(run)" compact :aria-label="`评测 ${run.id} 结果分布`" />
              </div>
            </button>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

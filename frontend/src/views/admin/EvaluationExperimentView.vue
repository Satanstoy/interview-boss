<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft, Ban, Radio, RefreshCw } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import AppCard from '@/components/common/AppCard.vue'
import EvalProgressBar from '@/components/business/EvalProgressBar.vue'
import EvalScoreBar from '@/components/business/EvalScoreBar.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cancelEvaluationExperiment, fetchEvaluationExperiment, streamEvaluationExperiment } from '@/services/evaluationApi.js'
import { evalRouteLocation, evaluationTargetLabel, formatDate, qualityStatusLabel, runDistribution, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const route = useRoute()
const router = useRouter()
const experiment = ref(null)
const loading = ref(true)
const error = ref('')
const lastSequence = ref(0)
const cancelling = ref(false)
let abortController = new AbortController()
let stopped = false

const terminal = computed(() => ['completed', 'failed', 'cancelled', 'expired'].includes(experiment.value?.status))
const progress = computed(() => {
  if (!experiment.value) return 0
  if (experiment.value.total_items) {
    return Math.round((((experiment.value.completed_items || 0) + (experiment.value.failed_items || 0)) / experiment.value.total_items) * 100)
  }
  if (!experiment.value.total_runs) return 0
  return Math.round((((experiment.value.completed_runs || 0) + (experiment.value.failed_runs || 0) + (experiment.value.cancelled_runs || 0)) / experiment.value.total_runs) * 100)
})

function progressSegmentsForRun(run) {
  const d = runDistribution(run)
  if (!d.total) return null
  return [
    { key: 'passed', label: '通过', value: d.passed, pct: d.pct.passed, color: 'bg-emerald-500' },
    { key: 'poor', label: '不佳', value: d.poor, pct: d.pct.poor, color: 'bg-amber-500' },
    { key: 'failed', label: '失败', value: d.failed, pct: d.pct.failed, color: 'bg-destructive' },
    { key: 'pending', label: '未完成', value: d.pending, pct: d.pct.pending, color: 'bg-muted-foreground/30', pattern: true },
  ]
}

async function load() {
  try {
    experiment.value = await fetchEvaluationExperiment(route.params.experimentId)
  } catch (err) {
    error.value = err.message || '评测实验详情加载失败'
  } finally {
    loading.value = false
  }
}

async function watchEvents() {
  while (!abortController.signal.aborted && !terminal.value && !stopped) {
    try {
      await streamEvaluationExperiment(route.params.experimentId, event => {
        if (stopped) return
        lastSequence.value = Math.max(lastSequence.value, Number(event.sequence || 0))
        load()
      }, { signal: abortController.signal, headers: lastSequence.value ? { 'Last-Event-ID': String(lastSequence.value) } : {} })
      if (stopped) return
      await load()
    } catch (err) {
      if (stopped || err.name === 'AbortError') return
      error.value = err.message || 'Experiment 进度流中断，正在重连'
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }
}

async function cancel() {
  cancelling.value = true
  error.value = ''
  try {
    await cancelEvaluationExperiment(route.params.experimentId)
    await load()
  } catch (err) {
    error.value = err.message || '取消评测实验失败'
  } finally {
    cancelling.value = false
  }
}

function openRun(run) {
  router.push(`/admin/evals/runs/${run.run_id}`)
}

watch(() => route.params.experimentId, async (n, o) => {
  if (n === o) return
  stopped = true
  abortController.abort()
  abortController = new AbortController()
  stopped = false
  lastSequence.value = 0
  loading.value = true
  await load()
  if (!terminal.value) watchEvents()
})

onMounted(async () => {
  await load()
  if (!terminal.value) watchEvents()
})

onUnmounted(() => {
  stopped = true
  abortController.abort()
})
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader :title="`测评实验 #${route.params.experimentId}`">
        <template #actions>
          <Button variant="ghost" @click="router.push(evalRouteLocation('/admin/evals/experiments', route.query))"><ArrowLeft class="mr-1.5 size-4" />返回测评实验</Button>
          <Button variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button>
          <Button v-if="experiment && !terminal" variant="destructive" :disabled="cancelling" @click="cancel"><Ban class="mr-1.5 size-4" />{{ cancelling ? '正在取消...' : '取消实验' }}</Button>
        </template>
      </EvaluationPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <p v-else-if="error && !experiment" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
      <template v-else-if="experiment">
        <AppCard class="mt-6" title="测评实验概览" description="这里看整体执行进度；不同评测目标的结果分别在下方查看。">
          <div class="flex flex-wrap items-center gap-3">
            <span class="text-xs text-muted-foreground">执行</span><Badge :class="statusClass(experiment.status)">{{ statusLabel(experiment.status) }}</Badge><span class="text-xs text-muted-foreground">结果</span><span class="text-sm text-muted-foreground">各目标质量分别查看</span>
            <span v-if="!terminal" class="inline-flex items-center gap-1 text-xs text-amber-600"><Radio class="size-3.5 animate-pulse" />实时跟踪中</span>
            <span class="text-sm text-muted-foreground">{{ experiment.total_runs }} 个目标评测</span>
            <span class="text-sm text-muted-foreground">{{ experiment.completed_runs || 0 }} 完成 · {{ experiment.failed_runs || 0 }} 失败 · {{ experiment.cancelled_runs || 0 }} 取消</span>
            <span class="ml-auto text-2xl font-semibold">{{ progress }}%</span>
          </div>
          <div class="mt-4"><EvalProgressBar :value="progress" size="md" /></div>
          <div class="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">Case 执行</span><div class="mt-1 font-medium">{{ (experiment.completed_items || 0) + (experiment.failed_items || 0) }} / {{ experiment.total_items || 0 }}</div></div>
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">运行参数</span><div class="mt-1 font-medium">{{ experiment.replication_count }} 次重跑 · seed {{ experiment.seed }}</div></div>
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">环境</span><div class="mt-1 break-all font-mono font-medium">{{ experiment.environment_fingerprint || '—' }}</div></div>
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">对比组</span><div class="mt-1 break-all font-mono font-medium">{{ experiment.comparison_group || '—' }}</div></div>
          </div>
          <p v-if="error" class="mt-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-700">{{ error }}</p>
        </AppCard>

        <AppCard class="mt-6" title="各目标评测结果" description="每个评测目标独立展示通过、表现不佳、失败和未完成的 Case。" no-padding>
          <div v-if="!experiment.runs?.length" class="p-8 text-center text-sm text-muted-foreground">暂无评测结果。</div>
          <div v-else class="divide-y divide-border/60">
            <div v-for="run in experiment.runs" :key="run.run_id" class="flex flex-wrap items-center gap-4 p-4">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2"><span class="font-medium">{{ evaluationTargetLabel(run.target_type) }}</span><span class="text-[11px] text-muted-foreground">执行</span><Badge :class="statusClass(run.status)">{{ statusLabel(run.status) }}</Badge><span class="text-[11px] text-muted-foreground">结果</span><Badge :class="statusClass(run.quality_status)">{{ qualityStatusLabel(run.quality_status) }}</Badge></div>
                <div class="mt-1 text-xs text-muted-foreground">评测 #{{ run.run_id }} · 被测 {{ run.target_release_key }} · 评测集 {{ run.benchmark_suite_release_key || run.evaluation_release_key || '—' }} · Harness {{ run.project_harness_key && run.project_harness_version ? `${run.project_harness_key}@${run.project_harness_version}` : '—' }}</div>
                <div class="mt-1 text-xs text-muted-foreground">执行状态：{{ statusLabel(run.status) }} · 创建于 {{ formatDate(run.created_at) }}</div>
              </div>
              <div class="w-48">
                <template v-if="progressSegmentsForRun(run) && (progressSegmentsForRun(run).reduce((a,b)=>a+b.value,0) > 0)">
                  <EvalProgressBar :segments="progressSegmentsForRun(run)" size="sm" />
                  <div class="mt-1 flex justify-between text-xs text-muted-foreground"><span class="inline-flex gap-1"><span class="text-emerald-600">{{ runDistribution(run).passed }} 通过</span><span class="text-amber-600">{{ runDistribution(run).poor }} 不佳</span><span class="text-destructive">{{ runDistribution(run).failed }} 失败</span><span v-if="runDistribution(run).pending" class="text-muted-foreground">{{ runDistribution(run).pending }} 未完成</span></span><span>{{ run.completed_items || 0 }}/{{ run.total_items || 0 }}</span></div>
                </template>
                <template v-else>
                  <div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span>{{ runProgress(run) }}%</span></div><EvalProgressBar :value="runProgress(run)" size="sm" />
                </template>
              </div>
              <div class="w-48"><EvalScoreBar :deterministic="run.score?.deterministic_mean" :judge="run.score?.judge_mean" :final="run.score?.final_mean" /></div>
              <Button size="sm" variant="outline" @click="openRun(run)">查看评测详情</Button>
            </div>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

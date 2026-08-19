import EvalScoreBar from '@/components/business/EvalScoreBar.vue'
<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ArrowLeft, Ban, Radio, RefreshCw } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { cancelEvaluationExperiment, fetchEvaluationExperiment, streamEvaluationExperiment } from '@/services/evaluationApi.js'
import { evaluationTargetLabel, formatDate, qualityStatusLabel, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const route = useRoute()
const router = useRouter()
const experiment = ref(null)
const loading = ref(true)
const error = ref('')
const lastSequence = ref(0)
const cancelling = ref(false)
const abortController = new AbortController()

const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(experiment.value?.status))
const progress = computed(() => {
  if (!experiment.value) return 0
  if (experiment.value.total_items) {
    return Math.round((((experiment.value.completed_items || 0) + (experiment.value.failed_items || 0)) / experiment.value.total_items) * 100)
  }
  if (!experiment.value.total_runs) return 0
  return Math.round((((experiment.value.completed_runs || 0) + (experiment.value.failed_runs || 0) + (experiment.value.cancelled_runs || 0)) / experiment.value.total_runs) * 100)
})

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
  while (!abortController.signal.aborted && !terminal.value) {
    try {
      await streamEvaluationExperiment(route.params.experimentId, event => {
        lastSequence.value = Math.max(lastSequence.value, Number(event.sequence || 0))
        load()
      }, { signal: abortController.signal, headers: lastSequence.value ? { 'Last-Event-ID': String(lastSequence.value) } : {} })
      await load()
    } catch (err) {
      if (err.name === 'AbortError') return
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

onMounted(async () => {
  await load()
  if (!terminal.value) watchEvents()
})

onUnmounted(() => abortController.abort())
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader :title="`评测实验 #${route.params.experimentId}`" description="一个 Experiment 管理多类 Eval 子 Run；这里汇总整体执行进度，并可进入任意子 Run 查看 Case 证据。" active-key="experiments">
        <template #actions>
          <Button variant="ghost" @click="router.push('/admin/evals/experiments')"><ArrowLeft class="mr-1.5 size-4" />返回测评实验</Button>
          <Button variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button>
          <Button v-if="experiment && !terminal" variant="destructive" :disabled="cancelling" @click="cancel"><Ban class="mr-1.5 size-4" />{{ cancelling ? '正在取消...' : '取消实验' }}</Button>
        </template>
      </EvaluationPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <p v-else-if="error && !experiment" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
      <template v-else-if="experiment">
        <AppCard class="mt-6" title="Experiment 总览" description="执行进度按已完成或失败的 Case 计算；质量是否通过由各子 Run 的 Hard Gate 和 Judge 结果决定。">
          <div class="flex flex-wrap items-center gap-3">
            <span class="text-xs text-muted-foreground">执行</span><span :class="['rounded-full px-2.5 py-1 text-sm', statusClass(experiment.status)]">{{ statusLabel(experiment.status) }}</span><span class="text-xs text-muted-foreground">质量</span><span :class="['rounded-full px-2.5 py-1 text-sm', statusClass(experiment.quality_status)]">{{ qualityStatusLabel(experiment.quality_status) }}</span>
            <span v-if="!terminal" class="inline-flex items-center gap-1 text-xs text-amber-600"><Radio class="size-3.5 animate-pulse" />实时跟踪中</span>
            <span class="text-sm text-muted-foreground">{{ experiment.total_runs }} 个子 Run</span>
            <span class="text-sm text-muted-foreground">{{ experiment.completed_runs || 0 }} 完成 · {{ experiment.failed_runs || 0 }} 失败 · {{ experiment.cancelled_runs || 0 }} 取消</span>
            <span class="ml-auto text-2xl font-semibold">{{ progress }}%</span>
          </div>
          <div class="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all duration-500" :style="{ width: `${progress}%` }" /></div>
          <div class="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">Case 执行</span><div class="mt-1 font-medium">{{ (experiment.completed_items || 0) + (experiment.failed_items || 0) }} / {{ experiment.total_items || 0 }}</div></div>
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">运行参数</span><div class="mt-1 font-medium">{{ experiment.replication_count }} 次重跑 · seed {{ experiment.seed }}</div></div>
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">环境</span><div class="mt-1 break-all font-mono font-medium">{{ experiment.environment_fingerprint || '—' }}</div></div>
            <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">对比组</span><div class="mt-1 break-all font-mono font-medium">{{ experiment.comparison_group || '—' }}</div></div>
          </div>
          <p v-if="error" class="mt-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-700">{{ error }}</p>
        </AppCard>

        <AppCard class="mt-6" title="子 Run" description="每个 Agent 都有独立 Run；进入详情可查看逐 Case 输入、输出、Hard Gate、Judge、Attempt 和 Artifact。" no-padding>
          <div v-if="!experiment.runs?.length" class="p-8 text-center text-sm text-muted-foreground">暂无子 Run。</div>
          <div v-else class="divide-y divide-border/60">
            <div v-for="run in experiment.runs" :key="run.run_id" class="flex flex-wrap items-center gap-4 p-4">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2"><span class="font-medium">{{ evaluationTargetLabel(run.target_type) }}</span><span class="text-[11px] text-muted-foreground">执行</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span class="text-[11px] text-muted-foreground">质量</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.quality_status)]">{{ qualityStatusLabel(run.quality_status) }}</span></div>
                <div class="mt-1 text-xs text-muted-foreground">Run #{{ run.run_id }} · 被测 {{ run.target_release_key }} · 评测 {{ run.evaluation_release_key || '—' }}</div>
                <div class="mt-1 text-xs text-muted-foreground">执行状态：{{ statusLabel(run.status) }} · 创建于 {{ formatDate(run.created_at) }}</div>
              </div>
              <div class="w-48"><div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span>{{ runProgress(run) }}%</span></div><div class="h-1.5 rounded-full bg-muted"><div class="h-full rounded-full bg-primary" :style="{ width: `${runProgress(run)}%` }" /></div></div>
              <div class="w-48"><EvalScoreBar :deterministic="run.score?.deterministic_mean" :judge="run.score?.judge_mean" :final="run.score?.final_mean" /></div>
              <Button size="sm" variant="outline" @click="openRun(run)">查看 Run 详情</Button>
            </div>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>
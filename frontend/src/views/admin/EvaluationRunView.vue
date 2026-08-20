<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Ban, CheckCircle2, Circle, Radio, RefreshCw } from '@lucide/vue'
import EvalCaseNavigator from '@/components/business/EvalCaseNavigator.vue'
import EvalEvidencePanel from '@/components/business/EvalEvidencePanel.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cancelEvaluationRun, fetchEvaluationEvidence, fetchEvaluationRun, retryFailedEvaluationRun, streamEvaluationRun } from '@/services/evaluationApi.js'
import { normalizeCaseEvidenceForLegacyPanel } from '@/services/evaluationSchemas.js'
import { casePrioritySort, qualityStatusLabel, runDistribution, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvalProgressBar from '@/components/business/EvalProgressBar.vue'
import { Badge } from '@/components/ui/badge'

const route = useRoute()
const router = useRouter()
const run = ref(null)
const loading = ref(true)
const error = ref('')
const lastSequence = ref(0)
const activeCaseId = ref(null)
const evidence = ref(null)
const evidenceLoading = ref(false)
const evidenceError = ref('')
const retrying = ref(false)
let abortController = new AbortController()
let stopped = false
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(run.value?.status))

const sortedItems = computed(() => casePrioritySort(run.value?.items || []))
const distribution = computed(() => runDistribution(run.value))
const progressSegments = computed(() => [
  { key: 'passed', label: '通过', value: distribution.value.passed, pct: distribution.value.pct.passed, color: 'bg-emerald-500' },
  { key: 'poor', label: '不佳', value: distribution.value.poor, pct: distribution.value.pct.poor, color: 'bg-amber-500' },
  { key: 'failed', label: '失败', value: distribution.value.failed, pct: distribution.value.pct.failed, color: 'bg-destructive' },
  { key: 'pending', label: '未完成', value: distribution.value.pending, pct: distribution.value.pct.pending, color: 'bg-muted-foreground/30', pattern: true },
])
function progressStats() {
  const d = distribution.value
  // 保留旧字段兼容，同时补充 poor/pending
  const items = run.value?.items || []
  const running = items.filter(i => i.status === 'running' || i.status === 'queued').length
  const judgePending = items.filter(i => i.status === 'completed' && i.judge_status === 'pending').length
  return { total: d.total, passed: d.passed, poor: d.poor, failed: d.failed, pending: d.pending, running, judgePending }
}

const phases = [
  { key: 'queue', label: '排队' },
  { key: 'e2e', label: 'E2E 执行' },
  { key: 'checks', label: '输出要求 / 硬性检查' },
  { key: 'judge', label: '固定质量评审' },
  { key: 'summary', label: '结果汇总' },
]

const phaseIndex = computed(() => {
  if (run.value?.status === 'created' || run.value?.status === 'queued') return 0
  if (run.value?.status === 'running') return 1
  if (run.value?.status === 'completed') return 4
  return 1
})

function phaseClass(index) {
  if (terminal.value && run.value?.status === 'failed' && index === phaseIndex.value) return 'border-destructive/30 bg-destructive/10 text-destructive'
  if (index < phaseIndex.value || (terminal.value && run.value?.status === 'completed')) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600'
  if (index === phaseIndex.value) return 'border-primary/30 bg-primary/10 text-primary'
  return 'border-border/70 bg-background text-muted-foreground'
}

function phaseIcon(index) {
  if (index < phaseIndex.value || (terminal.value && run.value?.status === 'completed')) return CheckCircle2
  return Circle
}


async function load() {
  try {
    run.value = await fetchEvaluationRun(route.params.runId)
    if (!activeCaseId.value && sortedItems.value.length) {
      activeCaseId.value = sortedItems.value[0].id
      loadEvidence(sortedItems.value[0])
    }
  } catch (err) {
    error.value = err.message || '评测详情加载失败'
  } finally {
    loading.value = false
  }
}

async function watchEvents() {
  while (!abortController.signal.aborted && !terminal.value && !stopped) {
    try {
      await streamEvaluationRun(route.params.runId, event => {
        if (stopped) return
        lastSequence.value = Math.max(lastSequence.value, Number(event.sequence || 0))
        load()
      }, { signal: abortController.signal, headers: lastSequence.value ? { 'Last-Event-ID': String(lastSequence.value) } : {} })
      if (stopped) return
      await load()
    } catch (err) {
      if (stopped || err.name === 'AbortError') return
      error.value = err.message || '进度流中断，正在重连'
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }
}

function navigateCase(direction) {
  const items = sortedItems.value
  if (!items.length) return
  const currentIndex = items.findIndex(i => i.id === activeCaseId.value)
  const nextIndex = direction === 'next'
    ? Math.min(currentIndex + 1, items.length - 1)
    : Math.max(currentIndex - 1, 0)
  if (nextIndex !== currentIndex) loadEvidence(items[nextIndex])
}

async function cancel() {
  try {
    await cancelEvaluationRun(route.params.runId)
    await load()
  } catch (err) {
    error.value = err.message || '取消评测失败'
  }
}

async function retryFailed() {
  retrying.value = true
  error.value = ''
  try {
    await retryFailedEvaluationRun(route.params.runId)
    await load()
  } catch (err) {
    error.value = err.message || '重跑失败 Case 失败'
  } finally {
    retrying.value = false
  }
}

async function loadEvidence(item) {
  if (!item) return
  activeCaseId.value = item.id
  evidence.value = null
  evidenceError.value = ''
  evidenceLoading.value = true
  try {
    evidence.value = normalizeCaseEvidenceForLegacyPanel(
      await fetchEvaluationEvidence(route.params.runId, item.id),
    )
  } catch (err) {
    evidenceError.value = err.message || 'Case 证据加载失败'
  } finally {
    evidenceLoading.value = false
  }
}

function handleKeydown(e) {
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
  if (e.key === 'j' || e.key === 'J') {
    e.preventDefault()
    navigateCase('next')
  } else if (e.key === 'k' || e.key === 'K') {
    e.preventDefault()
    navigateCase('prev')
  } else if (e.key === 'Escape') {
    activeCaseId.value = null
    evidence.value = null
  }
}

function onMobileSelect() {
  const item = (run.value?.items || []).find(i => i.id === Number(activeCaseId.value))
  if (item) loadEvidence(item)
}

watch(() => route.params.runId, async (newId, oldId) => {
  if (newId === oldId) return
  stopped = true
  abortController.abort()
  abortController = new AbortController()
  stopped = false
  lastSequence.value = 0
  run.value = null
  activeCaseId.value = null
  evidence.value = null
  loading.value = true
  error.value = ''
  await load()
  watchEvents()
})

onMounted(async () => {
  document.addEventListener('keydown', handleKeydown)
  await load()
  watchEvents()
})

onUnmounted(() => {
  stopped = true
  abortController.abort()
  document.removeEventListener('keydown', handleKeydown)
})
</script>
<template>
  <div class="h-full overflow-y-auto custom-scrollbar custom-scrollbar-always">
    <div class="border-b border-border/60 bg-background">
      <div class="mx-auto max-w-[1600px] px-4 py-3 sm:px-6 lg:px-8">
        <EvaluationPageHeader :title="`评测详情 #${route.params.runId}`" description="查看每个 Case 的执行进度、业务结果和质量指标。" active-key="experiments">
          <template #actions>
            <Button variant="ghost" @click="router.push('/admin/evals/experiments')"><ArrowLeft class="mr-1.5 size-4" />返回测评实验</Button>
            <Button v-if="run && terminal && run.failed_items > 0" variant="outline" :disabled="retrying" @click="retryFailed">{{ retrying ? '正在重新排队...' : '重跑失败 Case' }}</Button>
            <Button v-if="run && !terminal" variant="destructive" @click="cancel"><Ban class="mr-1.5 size-4" />取消评测</Button>
          </template>
        </EvaluationPageHeader>
      </div>
      <div v-if="run && !loading" class="mx-auto max-w-[1600px] px-4 pb-3 sm:px-6 lg:px-8">
        <div class="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 bg-muted/20 px-4 py-2.5">
          <span class="text-xs text-muted-foreground">执行</span>
          <Badge variant="default">{{ statusLabel(run.status) }}</Badge>
          <span class="text-xs text-muted-foreground">质量</span>
          <span :class="['rounded-full px-2.5 py-1 text-sm', statusClass(run.quality_status)]">{{ qualityStatusLabel(run.quality_status) }}</span>
          <span v-if="!terminal" class="inline-flex items-center gap-1 text-xs text-amber-600"><Radio class="size-3.5 animate-pulse" />实时跟踪中</span>
          <div class="hidden lg:block h-4 w-px bg-border/60" />
          <div aria-label="Case 进度" class="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Case {{ distribution.passed + distribution.poor + distribution.failed }} / {{ distribution.total }}</span>
            <span class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-emerald-500" />{{ distribution.passed }} 通过</span>
            <span v-if="distribution.poor" class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-amber-500" />{{ distribution.poor }} 不佳</span>
            <span class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-destructive" />{{ distribution.failed }} 失败</span>
            <span v-if="distribution.pending" class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-muted-foreground/30" />{{ distribution.pending }} 未完成</span>
            <span v-if="progressStats().running" class="text-amber-600">{{ progressStats().running }} 进行中</span>
          </div>
          <span class="ml-auto text-lg font-semibold">{{ distribution.total ? Math.round(((distribution.passed + distribution.poor + distribution.failed)/distribution.total)*100) : 0 }}%</span>
        </div>
        <div class="mt-2">
          <EvalProgressBar :segments="progressSegments" size="sm" show-legend />
        </div>
      </div>
      <!-- SSE 重连状态提示 -->
      <div v-if="error && !terminal" class="mx-auto max-w-[1600px] px-4 py-1.5 sm:px-6 lg:px-8">
        <div class="flex items-center gap-2 rounded-md bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700">
          <RefreshCw class="size-3 animate-spin" />{{ error }}
        </div>
      </div>
    </div>

    <!-- 分数汇总 + 阶段指示器 + 版本信息 -->
    <div v-if="run && !loading" class="mx-auto w-full max-w-[1600px] px-4 py-4 sm:px-6 lg:px-8">
      <div v-if="run.summary?.metric_summary" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div v-if="run.summary.metric_summary.score" class="rounded-lg bg-primary/5 p-3 text-xs">
          <div class="font-medium">整体分数</div>
          <div class="mt-1 text-muted-foreground">最终 {{ run.summary.metric_summary.score.final_mean == null ? '—' : Number(run.summary.metric_summary.score.final_mean).toFixed(3) }} · 规则检查 {{ run.summary.metric_summary.score.deterministic_mean == null ? '—' : Number(run.summary.metric_summary.score.deterministic_mean).toFixed(3) }} · 质量评审 {{ run.summary.metric_summary.score.judge_mean == null ? '—' : Number(run.summary.metric_summary.score.judge_mean).toFixed(3) }}</div>
        </div>
        <div v-if="run.summary.metric_summary.tool" class="rounded-lg bg-muted/40 p-3 text-xs">
          <div class="font-medium">工具调用效果</div>
          <div class="mt-1 text-muted-foreground">{{ run.summary.metric_summary.tool.call_count }} 次调用 · {{ run.summary.metric_summary.tool.failed_call_count }} 次失败</div>
        </div>
        <div v-if="run.summary.metric_summary.intent" class="rounded-lg bg-muted/40 p-3 text-xs">
          <div class="font-medium">意图识别效果</div>
          <div class="mt-1 text-muted-foreground">{{ run.summary.metric_summary.intent.observed_turn_count }} 轮 · 覆盖率 {{ run.summary.metric_summary.intent.intent_coverage == null ? '—' : `${Math.round(run.summary.metric_summary.intent.intent_coverage * 100)}%` }}</div>
        </div>
        <div v-if="run.summary.metric_summary.content" class="rounded-lg bg-muted/40 p-3 text-xs">
          <div class="font-medium">结构化抽取</div>
          <div class="mt-1 text-muted-foreground">字段覆盖 {{ Math.round(run.summary.metric_summary.content.field_coverage * 100) }}% · 题目召回 {{ Math.round((run.summary.metric_summary.content.question_recall || 0) * 100) }}%</div>
        </div>
      </div>
      <div class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <div aria-live="polite" v-for="(phase, index) in phases" :key="phase.key" :class="['rounded-lg border px-3 py-2', phaseClass(index)]">
          <div class="flex items-center gap-2 text-xs font-medium"><component :is="phaseIcon(index)" class="size-3.5" />{{ phase.label }}</div>
          <div class="mt-1 text-[11px] opacity-80">{{ index < phaseIndex ? '已完成' : index === phaseIndex ? '当前阶段' : '等待中' }}</div>
        </div>
      </div>
      <details class="mt-4 rounded-lg border border-border/60 px-3 py-2">
        <summary class="cursor-pointer text-xs font-medium text-muted-foreground">查看本次评测绑定的版本</summary>
        <div class="mt-3 grid gap-3 text-xs sm:grid-cols-3">
          <div>被测版本：<span class="font-mono text-foreground">{{ run.target_release_key }}</span></div>
          <div>完整评测版本：<span class="font-mono text-foreground">{{ run.evaluation_release_key || '历史组件模式' }}</span></div>
          <div>评分模型：<span class="font-mono text-foreground">{{ run.judge_model || run.judge_release_key || '—' }}</span></div>
          <div>执行器：<span class="font-mono text-foreground">{{ run.simulator_harness_release_key || '—' }}</span></div>
          <div>候选人模拟器：<span class="font-mono text-foreground">{{ run.candidate_simulator_release_key || '—' }}</span></div>
          <div>对比组：<span class="font-mono text-foreground">{{ run.comparison_group || '—' }}</span></div>
        </div>
      </details>
    </div>

    <!-- 主工作区 -->
    <div v-if="loading" class="flex min-h-[320px] items-center justify-center"><AsyncLoading /></div>
    <p v-else-if="error && !run" class="m-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
    <template v-else-if="run">
      <!-- 移动端 Case 切换下拉 -->
      <div class="mx-auto w-full max-w-[1600px] px-4 pb-2 md:hidden">
        <label class="flex items-center gap-2 text-sm">
          <span class="shrink-0 text-xs text-muted-foreground">Case：</span>
          <Select v-model="activeCaseId" @update:model-value="onMobileSelect">
  <SelectTrigger class="flex-1">
    <SelectValue placeholder="选择 Case" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem v-for="item in sortedItems" :key="item.id" :value="String(item.id)">
      <span :title="item.case_key">{{ item.case_key }}</span>
    </SelectItem>
  </SelectContent>
</Select>
        </label>
      </div>
      <div class="mx-auto flex w-full max-w-[1600px] gap-4 px-4 pb-6 sm:px-6 lg:px-8">
        <div class="hidden w-72 shrink-0 md:block">
          <div class="sticky top-4">
            <EvalCaseNavigator :items="run.items || []" :active-id="activeCaseId" sort-mode="priority" @select="id => { const item = (run.items || []).find(i => i.id === id); if (item) loadEvidence(item) }" />
          </div>
        </div>
        <div class="min-w-0 flex-1">
          <EvalEvidencePanel :item="run.items?.find(i => i.id === activeCaseId)" :evidence="evidence" :loading="evidenceLoading" :error="evidenceError" />
        </div>
      </div>
      <p v-if="error" class="mx-auto max-w-[1600px] px-4 pb-6 text-sm text-amber-700">{{ error }}</p>
    </template>
  </div>
</template>

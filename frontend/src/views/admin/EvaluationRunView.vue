<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Ban, CheckCircle2, Circle, Radio } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { cancelEvaluationRun, fetchEvaluationRun, streamEvaluationRun } from '@/services/evaluationApi.js'
import { checkStatusLabel, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const route = useRoute()
const router = useRouter()
const run = ref(null)
const loading = ref(true)
const error = ref('')
const lastSequence = ref(0)
const abortController = new AbortController()
const progress = computed(() => runProgress(run.value))
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(run.value?.status))
const phases = [
  { key: 'queue', label: '排队' },
  { key: 'e2e', label: 'E2E 执行' },
  { key: 'checks', label: 'Contract / Hard Gate' },
  { key: 'judge', label: 'Judge 评分' },
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

function metrics(item) {
  return item?.result?.observation?.payload || {}
}

function deterministicSummary(item) {
  const payload = metrics(item)
  if (payload.tool_metrics || payload.intent_metrics) {
    return `工具 ${payload.tool_metrics?.call_count || 0} 次 · 意图覆盖 ${payload.intent_metrics?.intent_coverage == null ? '—' : `${Math.round(payload.intent_metrics.intent_coverage * 100)}%`}`
  }
  if (payload.metrics?.field_coverage != null) {
    return `字段覆盖 ${Math.round(payload.metrics.field_coverage * 100)}% · 题目召回 ${Math.round((payload.metrics.question_recall || 0) * 100)}%`
  }
  if (payload.metrics?.source_fact_coverage != null) {
    return `事实覆盖 ${Math.round(payload.metrics.source_fact_coverage * 100)}% · 岗位匹配 ${Math.round((payload.metrics.target_alignment || 0) * 100)}%`
  }
  if (payload.metrics?.taxonomy_validity != null) {
    return `分类合法 ${Math.round(payload.metrics.taxonomy_validity * 100)}% · 标签准确 ${Math.round((payload.metrics.classification_accuracy || 0) * 100)}%`
  }
  return '—'
}

function scoreSummary(item) {
  const score = item?.result?.score || {}
  const sourceLabels = {
    hybrid: '混合',
    deterministic_only: '规则独立',
    judge_only: 'Judge 独立',
    deterministic_pending_judge: '规则已算',
  }
  const source = sourceLabels[score.score_source] || '未计算'
  const deterministic = score.deterministic_score == null ? '—' : Number(score.deterministic_score).toFixed(3)
  const judge = score.judge_score == null ? '—' : Number(score.judge_score).toFixed(3)
  return `${source} · 规则 ${deterministic} · Judge ${judge}`
}

async function load() {
  try {
    run.value = await fetchEvaluationRun(route.params.runId)
  } catch (err) {
    error.value = err.message || '评测详情加载失败'
  } finally {
    loading.value = false
  }
}

async function watchEvents() {
  while (!abortController.signal.aborted && !terminal.value) {
    try {
      await streamEvaluationRun(route.params.runId, event => {
        lastSequence.value = Math.max(lastSequence.value, Number(event.sequence || 0))
        load()
      }, { signal: abortController.signal, headers: lastSequence.value ? { 'Last-Event-ID': String(lastSequence.value) } : {} })
      await load()
    } catch (err) {
      if (err.name === 'AbortError') return
      error.value = err.message || '进度流中断，正在重连'
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }
}

async function cancel() {
  try {
    await cancelEvaluationRun(route.params.runId)
    await load()
  } catch (err) {
    error.value = err.message || '取消评测失败'
  }
}

onMounted(async () => {
  await load()
  watchEvents()
})

onUnmounted(() => abortController.abort())
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader :title="`评测运行 #${route.params.runId}`" description="跟踪完整 E2E 的进度；最终分数由规则指标与固定 Judge 按评测协议合成。" active-key="experiments">
        <template #actions><Button variant="ghost" @click="router.push('/admin/evals/experiments')"><ArrowLeft class="mr-1.5 size-4" />返回测评实验</Button><Button v-if="run && !terminal" variant="destructive" @click="cancel"><Ban class="mr-1.5 size-4" />取消评测</Button></template>
      </EvaluationPageHeader>
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <p v-else-if="error && !run" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
      <template v-else-if="run">
        <AppCard class="mt-6" title="当前执行阶段" description="实时进度来自可恢复 SSE 事件流，连接中断不会影响后台评测。">
          <div class="flex flex-wrap items-center gap-3"><span :class="['rounded-full px-2.5 py-1 text-sm', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span v-if="!terminal" class="inline-flex items-center gap-1 text-xs text-amber-600"><Radio class="size-3.5 animate-pulse" />实时跟踪中</span><span class="text-sm text-muted-foreground">已处理 {{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span class="ml-auto text-2xl font-semibold">{{ progress }}%</span></div>
          <div class="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all duration-500" :style="{ width: `${progress}%` }" /></div>
          <div v-if="run.summary?.metric_summary" class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div v-if="run.summary.metric_summary.score" class="rounded-lg bg-primary/5 p-3 text-xs"><div class="font-medium">混合主分（Run 汇总）</div><div class="mt-1 text-muted-foreground">最终 {{ run.summary.metric_summary.score.final_mean == null ? '—' : Number(run.summary.metric_summary.score.final_mean).toFixed(3) }} · 规则 {{ run.summary.metric_summary.score.deterministic_mean == null ? '—' : Number(run.summary.metric_summary.score.deterministic_mean).toFixed(3) }} · Judge {{ run.summary.metric_summary.score.judge_mean == null ? '—' : Number(run.summary.metric_summary.score.judge_mean).toFixed(3) }}</div></div><div v-if="run.summary.metric_summary.tool" class="rounded-lg bg-muted/40 p-3 text-xs"><div class="font-medium">工具调用效果（Run 汇总）</div><div class="mt-1 text-muted-foreground">{{ run.summary.metric_summary.tool.call_count }} 次调用 · {{ run.summary.metric_summary.tool.failed_call_count }} 次失败 · 结果使用率 {{ run.summary.metric_summary.tool.result_used_rate == null ? '—' : `${Math.round(run.summary.metric_summary.tool.result_used_rate * 100)}%` }}</div></div><div v-if="run.summary.metric_summary.intent" class="rounded-lg bg-muted/40 p-3 text-xs"><div class="font-medium">意图识别效果（Run 汇总）</div><div class="mt-1 text-muted-foreground">{{ run.summary.metric_summary.intent.observed_turn_count }} 轮记录 · 覆盖率 {{ run.summary.metric_summary.intent.intent_coverage == null ? '—' : `${Math.round(run.summary.metric_summary.intent.intent_coverage * 100)}%` }} · 准确率 {{ run.summary.metric_summary.intent.accuracy == null ? '—' : `${Math.round(run.summary.metric_summary.intent.accuracy * 100)}%` }}</div></div><div v-if="run.summary.metric_summary.content" class="rounded-lg bg-muted/40 p-3 text-xs"><div class="font-medium">结构化抽取（Run 汇总）</div><div class="mt-1 text-muted-foreground">字段覆盖 {{ Math.round(run.summary.metric_summary.content.field_coverage * 100) }}% · 题目召回 {{ Math.round(run.summary.metric_summary.content.question_recall * 100) }}%</div></div><div v-if="run.summary.metric_summary.resume" class="rounded-lg bg-muted/40 p-3 text-xs"><div class="font-medium">简历分析（Run 汇总）</div><div class="mt-1 text-muted-foreground">事实覆盖 {{ Math.round(run.summary.metric_summary.resume.source_fact_coverage * 100) }}% · 岗位匹配 {{ Math.round(run.summary.metric_summary.resume.target_alignment * 100) }}%</div></div><div v-if="run.summary.metric_summary.tagging" class="rounded-lg bg-muted/40 p-3 text-xs"><div class="font-medium">题目分类（Run 汇总）</div><div class="mt-1 text-muted-foreground">分类合法 {{ Math.round(run.summary.metric_summary.tagging.taxonomy_validity * 100) }}% · 标签准确 {{ Math.round(run.summary.metric_summary.tagging.classification_accuracy * 100) }}%</div></div></div>
          <div class="mt-6 grid gap-2 sm:grid-cols-5">
            <div v-for="(phase, index) in phases" :key="phase.key" :class="['rounded-lg border px-3 py-2', phaseClass(index)]"><div class="flex items-center gap-2 text-xs font-medium"><component :is="phaseIcon(index)" class="size-3.5" />{{ phase.label }}</div><div class="mt-1 text-[11px] opacity-80">{{ index < phaseIndex ? '已完成' : index === phaseIndex ? '当前阶段' : '等待中' }}</div></div>
          </div>
          <details class="mt-5 rounded-lg border border-border/60 px-3 py-2"><summary class="cursor-pointer text-xs font-medium text-muted-foreground">查看本次评测绑定的版本</summary><div class="mt-3 grid gap-3 text-xs sm:grid-cols-3"><div>被测版本：<span class="font-mono text-foreground">{{ run.target_release_key }}</span></div><div>完整评测版本：<span class="font-mono text-foreground">{{ run.evaluation_release_key || '历史组件模式' }}</span></div><div>固定 Judge：<span class="font-mono text-foreground">{{ run.judge_model || run.judge_release_key || '—' }}</span></div><div>执行器：<span class="font-mono text-foreground">{{ run.simulator_harness_release_key || '—' }}</span></div><div>候选人模拟器：<span class="font-mono text-foreground">{{ run.candidate_simulator_release_key || '—' }}</span></div><div>对比组：<span class="font-mono text-foreground">{{ run.comparison_group || '—' }}</span></div></div><div v-if="run.snapshot?.evaluation_release?.manifest" class="mt-4 rounded-lg bg-muted/40 p-3 text-xs"><div class="font-medium">本次快照已固定的关键指标</div><div class="mt-2 flex flex-wrap gap-2"><span v-if="run.snapshot.evaluation_release.manifest.tool_evaluation?.enabled" class="rounded-md bg-emerald-500/10 px-2 py-1 text-emerald-700">工具调用效果</span><span v-if="run.snapshot.evaluation_release.manifest.intent_evaluation?.enabled" class="rounded-md bg-emerald-500/10 px-2 py-1 text-emerald-700">意图识别效果</span></div></div></details>
          <p v-if="error" class="mt-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-700">{{ error }}</p>
        </AppCard>

        <AppCard class="mt-6" title="逐 Case 结果" description="先看执行状态和门禁结果；完整 transcript、工具轨迹和 Judge 原文在单个 Artifact 中查看。" no-padding>
          <div class="overflow-x-auto"><table class="w-full min-w-[1040px] text-left text-sm"><thead class="border-b border-border/60 bg-muted/30 text-xs text-muted-foreground"><tr><th class="px-5 py-3">Case / 重跑</th><th class="px-5 py-3">执行状态</th><th class="px-5 py-3">契约</th><th class="px-5 py-3">规则指标</th><th class="px-5 py-3">硬门禁</th><th class="px-5 py-3">Judge</th><th class="px-5 py-3">混合分</th></tr></thead><tbody class="divide-y divide-border/60"><tr v-for="item in run.items" :key="item.id" class="hover:bg-muted/20"><td class="px-5 py-3"><div class="font-medium">{{ item.case_key }}</div><div class="text-xs text-muted-foreground">第 {{ item.replication_index }} 次 · seed {{ item.seed }}</div></td><td class="px-5 py-3"><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(item.status)]">{{ statusLabel(item.status) }}</span></td><td class="px-5 py-3 text-xs">{{ checkStatusLabel(item.contract_status) }}</td><td class="px-5 py-3 text-xs"><div>{{ deterministicSummary(item) }}</div><div class="text-[11px] text-muted-foreground">工具 / 意图 / 结构化字段</div></td><td class="px-5 py-3 text-xs">{{ checkStatusLabel(item.hard_gate_status) }}</td><td class="px-5 py-3 text-xs">{{ checkStatusLabel(item.judge_status) }}</td><td class="px-5 py-3 font-mono"><div>{{ item.score == null ? '—' : Number(item.score).toFixed(3) }}</div><div class="font-sans text-[11px] text-muted-foreground">{{ scoreSummary(item) }}</div></td></tr></tbody></table></div>
          <div v-if="!run.items?.length" class="p-8 text-center text-sm text-muted-foreground">暂无 Case 结果。</div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

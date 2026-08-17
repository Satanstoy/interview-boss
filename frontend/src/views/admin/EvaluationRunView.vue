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
      <EvaluationPageHeader :title="`评测运行 #${route.params.runId}`" description="跟踪一场完整 E2E 的进度，并在需要时下钻到单个 Case 的执行证据。" active-key="experiments">
        <template #actions><Button variant="ghost" @click="router.push('/admin/evals/experiments')"><ArrowLeft class="mr-1.5 size-4" />返回测评实验</Button><Button v-if="run && !terminal" variant="destructive" @click="cancel"><Ban class="mr-1.5 size-4" />取消评测</Button></template>
      </EvaluationPageHeader>
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <p v-else-if="error && !run" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
      <template v-else-if="run">
        <AppCard class="mt-6" title="当前执行阶段" description="实时进度来自可恢复 SSE 事件流，连接中断不会影响后台评测。">
          <div class="flex flex-wrap items-center gap-3"><span :class="['rounded-full px-2.5 py-1 text-sm', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span v-if="!terminal" class="inline-flex items-center gap-1 text-xs text-amber-600"><Radio class="size-3.5 animate-pulse" />实时跟踪中</span><span class="text-sm text-muted-foreground">已处理 {{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span class="ml-auto text-2xl font-semibold">{{ progress }}%</span></div>
          <div class="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all duration-500" :style="{ width: `${progress}%` }" /></div>
          <div class="mt-6 grid gap-2 sm:grid-cols-5">
            <div v-for="(phase, index) in phases" :key="phase.key" :class="['rounded-lg border px-3 py-2', phaseClass(index)]"><div class="flex items-center gap-2 text-xs font-medium"><component :is="phaseIcon(index)" class="size-3.5" />{{ phase.label }}</div><div class="mt-1 text-[11px] opacity-80">{{ index < phaseIndex ? '已完成' : index === phaseIndex ? '当前阶段' : '等待中' }}</div></div>
          </div>
          <details class="mt-5 rounded-lg border border-border/60 px-3 py-2"><summary class="cursor-pointer text-xs font-medium text-muted-foreground">查看本次评测绑定的版本</summary><div class="mt-3 grid gap-3 text-xs sm:grid-cols-3"><div>被测版本：<span class="font-mono text-foreground">{{ run.target_release_key }}</span></div><div>评测题集：<span class="font-mono text-foreground">{{ run.benchmark_suite_release_key }}</span></div><div>评分模型：<span class="font-mono text-foreground">{{ run.judge_model || run.judge_release_key }}</span></div><div>执行器：<span class="font-mono text-foreground">{{ run.simulator_harness_release_key || '—' }}</span></div><div>候选人模拟器：<span class="font-mono text-foreground">{{ run.candidate_simulator_release_key || '—' }}</span></div><div>对比组：<span class="font-mono text-foreground">{{ run.comparison_group || '—' }}</span></div></div></details>
          <p v-if="error" class="mt-4 rounded-md bg-amber-500/10 p-3 text-sm text-amber-700">{{ error }}</p>
        </AppCard>

        <AppCard class="mt-6" title="逐 Case 结果" description="先看执行状态和门禁结果；完整 transcript、工具轨迹和 Judge 原文在单个 Artifact 中查看。" no-padding>
          <div class="overflow-x-auto"><table class="w-full min-w-[800px] text-left text-sm"><thead class="border-b border-border/60 bg-muted/30 text-xs text-muted-foreground"><tr><th class="px-5 py-3">Case / 重跑</th><th class="px-5 py-3">执行状态</th><th class="px-5 py-3">契约</th><th class="px-5 py-3">硬门禁</th><th class="px-5 py-3">Judge</th><th class="px-5 py-3">分数</th></tr></thead><tbody class="divide-y divide-border/60"><tr v-for="item in run.items" :key="item.id" class="hover:bg-muted/20"><td class="px-5 py-3"><div class="font-medium">{{ item.case_key }}</div><div class="text-xs text-muted-foreground">第 {{ item.replication_index }} 次 · seed {{ item.seed }}</div></td><td class="px-5 py-3"><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(item.status)]">{{ statusLabel(item.status) }}</span></td><td class="px-5 py-3 text-xs">{{ checkStatusLabel(item.contract_status) }}</td><td class="px-5 py-3 text-xs">{{ checkStatusLabel(item.hard_gate_status) }}</td><td class="px-5 py-3 text-xs">{{ checkStatusLabel(item.judge_status) }}</td><td class="px-5 py-3 font-mono">{{ item.score == null ? '—' : Number(item.score).toFixed(3) }}</td></tr></tbody></table></div>
          <div v-if="!run.items?.length" class="p-8 text-center text-sm text-muted-foreground">暂无 Case 结果。</div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

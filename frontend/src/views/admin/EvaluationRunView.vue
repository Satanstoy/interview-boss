<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Ban, Radio } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AppPageHeader from '@/components/common/AppPageHeader.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { cancelEvaluationRun, fetchEvaluationRun, streamEvaluationRun } from '@/services/evaluationApi.js'
import { runProgress, statusClass, statusLabel } from './evaluationShared.js'

const route = useRoute(); const router = useRouter()
const run = ref(null); const loading = ref(true); const error = ref(''); const lastSequence = ref(0); const abortController = new AbortController()
const progress = computed(() => runProgress(run.value))
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(run.value?.status))

async function load() {
  try { run.value = await fetchEvaluationRun(route.params.runId) } catch (err) { error.value = err.message || 'Run 详情加载失败' } finally { loading.value = false }
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
      error.value = err.message || 'SSE 连接中断，正在重连'
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }
}
async function cancel() { try { await cancelEvaluationRun(route.params.runId); await load() } catch (err) { error.value = err.message || '取消失败' } }
onMounted(async () => { await load(); watchEvents() })
onUnmounted(() => abortController.abort())
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar"><div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    <AppPageHeader :title="`Eval Run #${route.params.runId}`" description="查看固定评测上下文、实时进度、单 Case 结果和失败 Attempt。">
      <template #actions><Button variant="ghost" @click="router.push('/admin/evals/experiments')"><ArrowLeft class="mr-1.5 size-4" />返回实验</Button><Button v-if="run && !terminal" variant="destructive" @click="cancel"><Ban class="mr-1.5 size-4" />取消 Run</Button></template>
    </AppPageHeader>
    <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
    <p v-else-if="error && !run" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
    <template v-else-if="run">
      <AppCard class="mt-6"><div class="flex flex-wrap items-center gap-3"><span :class="['rounded-full px-2.5 py-1 text-sm', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span v-if="!terminal" class="inline-flex items-center gap-1 text-xs text-amber-600"><Radio class="size-3.5 animate-pulse" /> SSE 实时跟踪中</span><span class="text-sm text-muted-foreground">{{ run.completed_items }} / {{ run.total_items }} items</span><span class="ml-auto text-2xl font-semibold">{{ progress }}%</span></div><div class="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all duration-500" :style="{ width: `${progress}%` }" /></div><div class="mt-4 grid gap-3 text-xs text-muted-foreground sm:grid-cols-3"><div>Target：<span class="font-mono text-foreground">{{ run.target_release_key }}</span></div><div>Benchmark：<span class="font-mono text-foreground">{{ run.benchmark_suite_release_key }}</span></div><div>Judge：<span class="font-mono text-foreground">{{ run.judge_model || run.judge_release_key }}</span></div></div></AppCard>
      <AppCard class="mt-6" title="Items" no-padding><div class="overflow-x-auto"><table class="w-full min-w-[800px] text-left text-sm"><thead class="border-b border-border/60 bg-muted/30 text-xs text-muted-foreground"><tr><th class="px-5 py-3">Case</th><th class="px-5 py-3">状态</th><th class="px-5 py-3">Contract</th><th class="px-5 py-3">Hard Gate</th><th class="px-5 py-3">Judge</th><th class="px-5 py-3">Score</th></tr></thead><tbody class="divide-y divide-border/60"><tr v-for="item in run.items" :key="item.id"><td class="px-5 py-3"><div class="font-medium">{{ item.case_key }}</div><div class="text-xs text-muted-foreground">replication {{ item.replication_index }} · seed {{ item.seed }}</div></td><td class="px-5 py-3"><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(item.status)]">{{ statusLabel(item.status) }}</span></td><td class="px-5 py-3 text-xs">{{ item.contract_status }}</td><td class="px-5 py-3 text-xs">{{ item.hard_gate_status }}</td><td class="px-5 py-3 text-xs">{{ item.judge_status }}</td><td class="px-5 py-3 font-mono">{{ item.score == null ? '—' : Number(item.score).toFixed(3) }}</td></tr></tbody></table></div><div v-if="!run.items?.length" class="p-8 text-center text-sm text-muted-foreground">暂无 Item。</div></AppCard>
    </template>
  </div></div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { BookOpen, ChevronDown, ClipboardCheck, ShieldCheck } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { fetchEvaluationBenchmarks } from '@/services/evaluationApi.js'
import { releaseTypeLabel, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const suites = ref([])
const loading = ref(true)
const error = ref('')
const opened = ref(null)

async function load() {
  try {
    suites.value = (await fetchEvaluationBenchmarks()).suites || []
  } catch (err) {
    error.value = err.message || 'Benchmark 加载失败'
  } finally {
    loading.value = false
  }
}

function toggle(id) {
  opened.value = opened.value === id ? null : id
}

onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader title="Benchmark：这套题集测什么" description="先看每套题集覆盖的场景和质量要求；展开 Case 后，再查看候选人可见输入与底层契约。" active-key="benchmarks" />
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <p v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
      <div v-else class="mt-6 space-y-5">
        <AppCard v-for="suite in suites" :key="suite.id" no-padding>
          <button type="button" class="flex w-full items-start gap-4 p-5 text-left" @click="toggle(suite.id)">
            <div class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><BookOpen class="size-5" /></div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2"><span class="font-semibold">{{ suite.release_key }}</span><span class="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600">{{ statusLabel(suite.release_status) }}</span></div>
              <p class="mt-1 text-sm text-muted-foreground">{{ suite.description || '固定的评测场景与质量要求。' }}</p>
              <div class="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3"><span><strong class="font-medium text-foreground">{{ suite.cases?.length || 0 }}</strong> 个 Case</span><span>评分模型：<strong class="font-medium text-foreground">{{ suite.judge_model || '按运行绑定' }}</strong></span><span>版本类型：{{ releaseTypeLabel('benchmark_suite') }}</span></div>
            </div>
            <ChevronDown :class="['mt-1 size-5 shrink-0 transition-transform', opened === suite.id ? 'rotate-180' : '']" />
          </button>
          <div v-if="opened === suite.id" class="border-t border-border/60 px-5 pb-5">
            <div class="flex items-center gap-2 py-4 text-sm font-medium"><ClipboardCheck class="size-4 text-primary" />这套题集如何判断质量</div>
            <div v-for="item in suite.cases" :key="item.id" class="border-b border-border/50 py-4 last:border-0">
              <div class="flex flex-wrap items-center gap-2"><span class="font-medium">{{ item.case_key }}</span><span class="text-xs text-muted-foreground">场景：{{ item.scenario_key || '未命名场景' }}</span><span class="ml-auto text-xs text-muted-foreground">输入已固化</span></div>
              <div class="mt-3 grid gap-3 text-xs sm:grid-cols-3">
                <div class="rounded-lg bg-muted/40 p-3"><div class="mb-1 font-medium text-foreground">候选人可见输入</div><div class="text-muted-foreground">Simulator 只能看到本 Case 明确允许的上下文。</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><div class="mb-1 flex items-center gap-1 font-medium text-foreground"><ShieldCheck class="size-3.5 text-emerald-600" />硬约束</div><div class="text-muted-foreground">{{ item.contract?.hard_assertions?.length || 0 }} 个必检条件</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><div class="mb-1 font-medium text-foreground">质量维度</div><div class="text-muted-foreground">{{ Object.keys(item.contract?.rubric || {}).join('、') || '未配置' }}</div></div>
              </div>
              <details class="mt-3 rounded-lg border border-border/60 px-3 py-2">
                <summary class="cursor-pointer text-xs font-medium text-muted-foreground">查看输入快照与详细要求</summary>
                <div class="mt-3 grid gap-3 text-xs md:grid-cols-2">
                  <div><div class="mb-1 font-medium text-foreground">candidate_view</div><pre class="max-h-36 overflow-auto whitespace-pre-wrap text-muted-foreground">{{ JSON.stringify(item.input_snapshot?.candidate_view || {}, null, 2) }}</pre></div>
                  <div><div class="mb-1 font-medium text-foreground">quality_requirements</div><pre class="max-h-36 overflow-auto whitespace-pre-wrap text-muted-foreground">{{ JSON.stringify(item.contract?.quality_requirements || [], null, 2) }}</pre></div>
                </div>
              </details>
            </div>
          </div>
        </AppCard>
        <div v-if="!suites.length" class="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">暂无 Benchmark Suite。</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { BookOpen, ChevronDown, ShieldCheck } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AppPageHeader from '@/components/common/AppPageHeader.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { fetchEvaluationBenchmarks } from '@/services/evaluationApi.js'

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
function toggle(id) { opened.value = opened.value === id ? null : id }
onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar"><div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    <AppPageHeader title="Benchmark" description="查看 Git 版本化的 Suite、Case、硬断言和 rubric。候选人 simulator 只会收到 candidate_view。" />
    <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
    <p v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
    <div v-else class="mt-6 space-y-5">
      <AppCard v-for="suite in suites" :key="suite.id" no-padding>
        <button type="button" class="flex w-full items-center gap-4 p-5 text-left" @click="toggle(suite.id)">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><BookOpen class="size-5" /></div>
          <div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="font-semibold">{{ suite.release_key }}</span><span class="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600">{{ suite.release_status }}</span></div><div class="mt-1 text-sm text-muted-foreground">{{ suite.description }} · {{ suite.cases?.length || 0 }} Cases · Judge: {{ suite.judge_model }}</div></div>
          <ChevronDown :class="['size-5 transition-transform', opened === suite.id ? 'rotate-180' : '']" />
        </button>
        <div v-if="opened === suite.id" class="border-t border-border/60 px-5 pb-5">
          <div v-for="item in suite.cases" :key="item.id" class="border-b border-border/50 py-4 last:border-0">
            <div class="flex flex-wrap items-center gap-2"><span class="font-medium">{{ item.case_key }}</span><span class="text-xs text-muted-foreground">{{ item.scenario_key }}</span><span class="ml-auto text-xs text-muted-foreground">digest {{ item.input_digest?.slice(0, 12) }}</span></div>
            <div class="mt-3 grid gap-3 text-xs md:grid-cols-2"><div class="rounded-lg bg-muted/40 p-3"><div class="mb-1 font-medium text-foreground">candidate_view</div><pre class="max-h-36 overflow-auto whitespace-pre-wrap text-muted-foreground">{{ JSON.stringify(item.input_snapshot?.candidate_view || {}, null, 2) }}</pre></div><div class="rounded-lg bg-muted/40 p-3"><div class="mb-1 flex items-center gap-1 font-medium text-foreground"><ShieldCheck class="size-3.5 text-emerald-600" /> contract</div><div class="text-muted-foreground">{{ item.contract?.hard_assertions?.length || 0 }} 个硬断言 · rubric: {{ Object.keys(item.contract?.rubric || {}).join('、') || '未配置' }}</div><pre class="mt-2 max-h-36 overflow-auto whitespace-pre-wrap text-muted-foreground">{{ JSON.stringify(item.contract?.quality_requirements || [], null, 2) }}</pre></div></div>
          </div>
        </div>
      </AppCard>
      <div v-if="!suites.length" class="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">暂无 Benchmark Suite。</div>
    </div>
  </div></div>
</template>

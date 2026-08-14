<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Play, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AppPageHeader from '@/components/common/AppPageHeader.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createEvaluationRun, fetchEvaluationReleases, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { formatDate, runProgress, statusClass, statusLabel } from './evaluationShared.js'

const router = useRouter()
const releases = ref([])
const runs = ref([])
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const form = ref({ target: '', suite: '', protocol: '', judge: '', harness: '', simulator: '', replication: 5, seed: 1, environment: 'local-baseline', comparison: '' })

const byType = computed(() => type => releases.value.filter(release => release.release_type === type && release.status === 'published'))

function chooseDefaults() {
  const defaults = {
    target: 'interview-agent@1.0', suite: 'interview-e2e-suite@1.0', protocol: 'eval-protocol@1.0',
    judge: 'judge@1.0', harness: 'interview-harness@1.0', simulator: 'candidate-simulator@1.0',
  }
  for (const [field, key] of Object.entries(defaults)) {
    const found = releases.value.find(item => item.release_key === key)
    if (found) form.value[field] = String(found.id)
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [releaseData, runData] = await Promise.all([fetchEvaluationReleases(), fetchEvaluationRuns()])
    releases.value = releaseData.releases || []
    runs.value = runData.runs || []
    chooseDefaults()
  } catch (err) {
    error.value = err.message || '评测实验加载失败'
  } finally {
    loading.value = false
  }
}

async function submit() {
  submitting.value = true
  error.value = ''
  try {
    const result = await createEvaluationRun({
      target_release_id: Number(form.value.target), benchmark_suite_release_id: Number(form.value.suite),
      eval_protocol_release_id: Number(form.value.protocol), judge_release_id: Number(form.value.judge),
      simulator_harness_release_id: Number(form.value.harness), candidate_simulator_release_id: Number(form.value.simulator),
      replication_count: Number(form.value.replication), seed: Number(form.value.seed),
      environment_fingerprint: form.value.environment, comparison_group: form.value.comparison,
    })
    router.push(`/admin/evals/runs/${result.run_id}`)
  } catch (err) {
    error.value = err.message || '创建 Eval Run 失败'
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar"><div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    <AppPageHeader title="测评实验" description="选择已发布版本，生成固定 Batch，并把每个 Benchmark Case 按 replication 执行。" />
    <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
    <div v-else class="mt-6 grid gap-6 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      <AppCard title="创建 Eval Run" description="同一批次的上下文和参数会被固化，后续版本变更不会改写历史记录。">
        <form class="space-y-4" @submit.prevent="submit">
          <label v-for="field in [{ key: 'target', label: 'Target Agent / Workflow', type: 'target' }, { key: 'suite', label: 'Benchmark Suite', type: 'benchmark_suite' }, { key: 'protocol', label: 'Eval Protocol', type: 'eval_protocol' }, { key: 'judge', label: 'Judge Release', type: 'judge' }, { key: 'harness', label: 'Simulator Harness', type: 'simulator_harness' }, { key: 'simulator', label: 'Candidate Simulator', type: 'candidate_simulator' }]" :key="field.key" class="block text-sm font-medium">
            {{ field.label }}
            <select v-model="form[field.key]" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm" required>
              <option value="" disabled>请选择已发布版本</option><option v-for="release in byType(field.type)" :key="release.id" :value="String(release.id)">{{ release.release_key }}</option>
            </select>
          </label>
          <div class="grid grid-cols-2 gap-3">
            <label class="text-sm font-medium">Replication<input v-model.number="form.replication" type="number" min="1" max="100" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm" /></label>
            <label class="text-sm font-medium">Seed<input v-model.number="form.seed" type="number" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm" /></label>
          </div>
          <label class="block text-sm font-medium">Environment fingerprint<Input v-model="form.environment" class="mt-1.5" placeholder="local-baseline" /></label>
          <label class="block text-sm font-medium">Comparison group（可选）<Input v-model="form.comparison" class="mt-1.5" placeholder="release-ab-2026-08" /></label>
          <p v-if="error" class="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p>
          <Button class="w-full" type="submit" :disabled="submitting"><Play class="mr-1.5 size-4" />{{ submitting ? '正在创建...' : '创建并开始评测' }}</Button>
        </form>
      </AppCard>

      <AppCard title="Eval Runs" description="Run 进入队列后，执行进度会在详情页通过 SSE 实时更新。" no-padding>
        <div class="flex items-center justify-end border-b border-border/60 p-3"><Button size="sm" variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button></div>
        <div v-if="!runs.length" class="p-8 text-center text-sm text-muted-foreground">还没有 Run。</div>
        <div v-else class="divide-y divide-border/60">
          <button v-for="run in runs" :key="run.id" type="button" class="flex w-full items-center gap-4 p-4 text-left hover:bg-muted/40" @click="router.push(`/admin/evals/runs/${run.id}`)">
            <div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="font-medium">Run #{{ run.id }}</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span v-if="run.comparison_group" class="text-xs text-muted-foreground">A/B: {{ run.comparison_group }}</span></div><div class="mt-1 text-xs text-muted-foreground">{{ run.target_release_key }} · {{ run.benchmark_suite_release_key }} · {{ formatDate(run.created_at) }}</div></div>
            <div class="w-32"><div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }}</span><span>{{ runProgress(run) }}%</span></div><div class="h-1.5 rounded-full bg-muted"><div class="h-full rounded-full bg-primary" :style="{ width: `${runProgress(run)}%` }" /></div></div>
          </button>
        </div>
      </AppCard>
    </div>
  </div></div>
</template>

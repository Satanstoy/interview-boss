<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Play, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createEvaluationRun, fetchEvaluationReleases, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { formatDate, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvaluationStepCard from './EvaluationStepCard.vue'

const router = useRouter()
const releases = ref([])
const runs = ref([])
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const form = ref({ target: '', suite: '', protocol: '', judge: '', harness: '', simulator: '', replication: 5, seed: 1, environment: 'local-baseline', comparison: '' })

const releaseFields = [
  { key: 'suite', label: '评测题集', type: 'benchmark_suite', help: '固定要测的场景、Case 和质量要求。' },
  { key: 'protocol', label: '评测规则', type: 'eval_protocol', help: '固定重跑次数、聚合方式和通过门槛。' },
  { key: 'judge', label: '评分模型', type: 'judge', help: '固定 Judge Model，避免历史分数漂移。' },
  { key: 'harness', label: '模拟面试执行器', type: 'simulator_harness', help: '负责多轮 E2E、工具和轨迹采集。' },
  { key: 'simulator', label: '候选人模拟器', type: 'candidate_simulator', help: '负责生成候选人在面试中的行为。' },
]

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
    error.value = err.message || '创建评测失败'
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader title="发起一次评测" description="选择一个被测版本和一套固定基线，系统会创建不可变评测批次并启动完整 E2E。" active-key="experiments" />
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else class="mt-6 grid gap-6 xl:grid-cols-[minmax(0,500px)_minmax(0,1fr)]">
        <AppCard title="评测配置" description="同一批次的版本和参数会被固化，之后的代码变更不会改写这次历史记录。">
          <form class="space-y-3" @submit.prevent="submit">
            <EvaluationStepCard :number="1" title="选择被测版本" description="这是本次要回答的核心问题：哪一个 Agent、Workflow 或 Pipeline 要接受评测？">
              <label class="block text-sm font-medium" for="eval-target">被测版本（Agent / Workflow）</label>
              <select id="eval-target" v-model="form.target" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" required>
                <option value="" disabled>请选择已发布版本</option>
                <option v-for="release in byType('target')" :key="release.id" :value="String(release.id)">{{ release.release_key }}</option>
              </select>
              <p class="mt-1.5 text-xs text-muted-foreground">只选择一个目标版本；不同 Agent / Workflow 应分别建立自己的评测运行。</p>
            </EvaluationStepCard>

            <EvaluationStepCard :number="2" title="选择评测基线" description="下面的组件共同决定评测测什么、怎么跑、如何评分，不能只换其中一项来做公平比较。">
              <div class="space-y-3">
                <label v-for="field in releaseFields" :key="field.key" class="block text-sm font-medium">
                  {{ field.label }}
                  <select v-model="form[field.key]" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" required>
                    <option value="" disabled>请选择已发布版本</option>
                    <option v-for="release in byType(field.type)" :key="release.id" :value="String(release.id)">{{ release.release_key }}</option>
                  </select>
                  <span class="mt-1 block text-xs font-normal text-muted-foreground">{{ field.help }}</span>
                </label>
              </div>
            </EvaluationStepCard>

            <EvaluationStepCard :number="3" title="固定运行参数" description="这些参数会写入评测批次，保证后续可以复现和比较。">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="text-sm font-medium">每个 Case 重跑次数<input v-model.number="form.replication" type="number" min="1" max="100" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" /></label>
                <label class="text-sm font-medium">随机种子<input v-model.number="form.seed" type="number" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" /></label>
              </div>
              <label class="mt-3 block text-sm font-medium">运行环境标识<Input v-model="form.environment" class="mt-1.5" placeholder="local-baseline" /></label>
              <label class="mt-3 block text-sm font-medium">版本对比组（可选）<Input v-model="form.comparison" class="mt-1.5" placeholder="release-ab-2026-08" /></label>
              <p class="mt-1.5 text-xs text-muted-foreground">只有同一对比组、同一评测基线下的两个目标版本，才适合做人工 A/B。</p>
            </EvaluationStepCard>

            <p v-if="error" class="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p>
            <Button class="w-full" type="submit" :disabled="submitting"><Play class="mr-1.5 size-4" />{{ submitting ? '正在创建...' : '创建并开始评测' }}</Button>
          </form>
        </AppCard>

        <AppCard title="历史评测" description="选择一条记录查看实时进度、逐 Case 证据和最终聚合结果。" no-padding>
          <div class="flex items-center justify-end border-b border-border/60 p-3"><Button size="sm" variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button></div>
          <div v-if="!runs.length" class="p-8 text-center text-sm text-muted-foreground">还没有评测记录。</div>
          <div v-else class="divide-y divide-border/60">
            <button v-for="run in runs" :key="run.id" type="button" class="flex w-full items-center gap-4 p-4 text-left hover:bg-muted/40" @click="router.push(`/admin/evals/runs/${run.id}`)">
              <div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="font-medium">评测 #{{ run.id }}</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span v-if="run.comparison_group" class="text-xs text-muted-foreground">对比组：{{ run.comparison_group }}</span></div><div class="mt-1 text-xs text-muted-foreground">被测版本：{{ run.target_release_key }} · {{ formatDate(run.created_at) }}</div></div>
              <div class="w-36"><div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span>{{ runProgress(run) }}%</span></div><div class="h-1.5 rounded-full bg-muted"><div class="h-full rounded-full bg-primary" :style="{ width: `${runProgress(run)}%` }" /></div></div>
            </button>
          </div>
        </AppCard>
      </div>
    </div>
  </div>
</template>

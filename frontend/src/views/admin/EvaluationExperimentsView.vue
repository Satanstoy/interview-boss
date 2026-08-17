<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CheckCircle2, Play, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createEvaluationRun, fetchEvaluationReleases, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { evaluationTargetLabel, formatDate, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvaluationStepCard from './EvaluationStepCard.vue'
import EvaluationTargetPicker from './EvaluationTargetPicker.vue'

const router = useRouter()
const releases = ref([])
const runs = ref([])
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const form = ref({ target: '', evaluation: '', replication: 5, seed: 1, environment: 'local-baseline', comparison: '' })
const selectedTargetType = ref('interview')

const published = computed(() => releases.value.filter(release => release.status === 'published'))
const targets = computed(() => published.value.filter(release => release.release_type === 'target'))
const evaluations = computed(() => published.value.filter(release => (
  release.release_type === 'evaluation'
  && (!selectedTargetType.value || !release.target_type || release.target_type === selectedTargetType.value)
)))
const selectedEvaluation = computed(() => releases.value.find(release => String(release.id) === String(form.value.evaluation)))

function manifestOf(release) {
  if (release?.manifest && typeof release.manifest === 'object') return release.manifest
  try { return JSON.parse(release?.manifest_json || '{}') } catch { return {} }
}

const evaluationConfig = computed(() => {
  const manifest = manifestOf(selectedEvaluation.value)
  return {
    benchmark: manifest.benchmark?.suite_key || '—',
    judge: manifest.judge?.model || selectedEvaluation.value?.judge_model || '—',
    harness: manifest.simulator_harness?.version || '1.0',
    simulator: manifest.candidate_simulator?.model || '—',
    tool: Boolean(manifest.tool_evaluation?.enabled),
    intent: Boolean(manifest.intent_evaluation?.enabled),
  }
})

function chooseDefaults() {
  const target = targets.value.find(release => release.release_key === 'interview-agent@1.0') || targets.value[0]
  if (target) {
    form.value.target = String(target.id)
    selectedTargetType.value = target.target_type || 'interview'
  }
  const evaluation = evaluations.value.find(release => release.release_key === 'interview-eval@1.0') || evaluations.value[0]
  if (evaluation) form.value.evaluation = String(evaluation.id)
}

function selectTargetType(type) {
  selectedTargetType.value = type
  const target = targets.value.find(release => release.target_type === type)
  if (target) form.value.target = String(target.id)
  const evaluation = evaluations.value.find(release => release.target_type === type) || evaluations.value[0]
  form.value.evaluation = evaluation ? String(evaluation.id) : ''
}

function selectTarget() {
  const target = targets.value.find(release => String(release.id) === String(form.value.target))
  selectedTargetType.value = target?.target_type || ''
  const evaluation = evaluations.value.find(release => String(release.id) === String(form.value.evaluation)) || evaluations.value[0]
  form.value.evaluation = evaluation ? String(evaluation.id) : ''
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
  if (!form.value.target || !form.value.evaluation) {
    error.value = '请选择被测版本和完整评测版本。'
    return
  }
  if (!selectedTargetType.value) {
    error.value = '当前被测版本没有评测对象类型，请先选择一个已接入的目标版本。'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const result = await createEvaluationRun({
      target_release_id: Number(form.value.target),
      evaluation_release_id: Number(form.value.evaluation),
      replication_count: Number(form.value.replication),
      seed: Number(form.value.seed),
      environment_fingerprint: form.value.environment,
      comparison_group: form.value.comparison,
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
      <EvaluationPageHeader title="发起一次评测" description="选择一个被测版本和一个完整评测版本，系统会冻结所有参数，启动可恢复的多轮 E2E。" active-key="experiments" />
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else class="mt-6 grid gap-6 xl:grid-cols-[minmax(0,500px)_minmax(0,1fr)]">
        <AppCard title="评测配置" description="一个完整评测版本就是一套一致的题集、规则、模型和 Harness；同一批次内不会混用。">
          <form class="space-y-3" @submit.prevent="submit">
            <EvaluationTargetPicker :model-value="selectedTargetType" @update:model-value="selectTargetType" />
            <EvaluationStepCard :number="1" title="选择被测版本" description="决定这次要测哪个 Agent、Workflow 或 Pipeline。">
              <label class="block text-sm font-medium" for="eval-target">被测版本（{{ evaluationTargetLabel(selectedTargetType) }}）</label>
              <select id="eval-target" v-model="form.target" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" required @change="selectTarget">
                <option value="" disabled>请选择已发布版本</option>
                <option v-for="release in targets.filter(item => !selectedTargetType || item.target_type === selectedTargetType)" :key="release.id" :value="String(release.id)">{{ release.release_key }}</option>
              </select>
              <p class="mt-1.5 text-xs text-muted-foreground">每个 Agent / Workflow 独立建立自己的评测 Run，便于后续做 A/B。</p>
            </EvaluationStepCard>

            <EvaluationStepCard :number="2" title="选择完整评测版本" description="这一个版本整体固定 Benchmark、Judge、模拟器、Harness，以及工具调用和意图识别指标。">
              <label class="block text-sm font-medium" for="eval-release">完整评测版本</label>
              <select id="eval-release" v-model="form.evaluation" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" required>
                <option value="" disabled>请选择已发布版本</option>
                <option v-for="release in evaluations" :key="release.id" :value="String(release.id)">{{ release.release_key }}</option>
              </select>
              <div class="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">评测题集</span><div class="mt-1 font-medium">{{ evaluationConfig.benchmark }}</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">固定 Judge</span><div class="mt-1 break-all font-mono font-medium">{{ evaluationConfig.judge }}</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">执行器 / 候选人</span><div class="mt-1 font-medium">{{ evaluationConfig.harness }} · {{ evaluationConfig.simulator }}</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">明确指标</span><div class="mt-1 flex flex-wrap gap-1.5"><span v-if="evaluationConfig.tool" class="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 class="size-3.5" />工具调用效果</span><span v-if="evaluationConfig.intent" class="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 class="size-3.5" />意图识别效果</span></div></div>
              </div>
            </EvaluationStepCard>

            <EvaluationStepCard :number="3" title="固定运行参数" description="这些参数会写入批次指纹，保证多次 E2E 可以复现和比较。">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="text-sm font-medium">每个 Case 重跑次数<input v-model.number="form.replication" type="number" min="1" max="100" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" /></label>
                <label class="text-sm font-medium">随机种子<input v-model.number="form.seed" type="number" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" /></label>
              </div>
              <label class="mt-3 block text-sm font-medium">运行环境标识<Input v-model="form.environment" class="mt-1.5" placeholder="local-baseline" /></label>
              <label class="mt-3 block text-sm font-medium">版本对比组（可选）<Input v-model="form.comparison" class="mt-1.5" placeholder="release-ab-2026-08" /></label>
              <p class="mt-1.5 text-xs text-muted-foreground">人工 A/B 必须使用同一完整评测版本、同一 Case 和同一输入快照，只改变被测版本。</p>
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
              <div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="font-medium">评测 #{{ run.id }}</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span v-if="run.comparison_group" class="text-xs text-muted-foreground">对比组：{{ run.comparison_group }}</span></div><div class="mt-1 text-xs text-muted-foreground">被测：{{ run.target_release_key }} · 评测：{{ run.evaluation_release_key || '历史组件模式' }} · {{ formatDate(run.created_at) }}</div></div>
              <div class="w-36"><div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span>{{ runProgress(run) }}%</span></div><div class="h-1.5 rounded-full bg-muted"><div class="h-full rounded-full bg-primary" :style="{ width: `${runProgress(run)}%` }" /></div></div>
            </button>
          </div>
        </AppCard>
      </div>
    </div>
  </div>
</template>

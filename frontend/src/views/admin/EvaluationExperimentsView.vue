<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, CheckCircle2, Play, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createEvaluationExperiment, createEvaluationRun, fetchEvaluationBenchmarks, fetchEvaluationCapabilities, fetchEvaluationExperiments, fetchEvaluationReleases, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { evaluationTargetLabel, formatDate, qualityStatusLabel, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvaluationStepCard from './EvaluationStepCard.vue'
import EvaluationTargetPicker from './EvaluationTargetPicker.vue'

const router = useRouter()
const route = useRoute()
const releases = ref([])
const capabilities = ref([])
const runs = ref([])
const experiments = ref([])
const benchmarks = ref([])
const loading = ref(true)
const submitting = ref(false)
const experimentSubmitting = ref(false)
const error = ref('')
const form = ref({ target: '', evaluation: '', replication: 5, seed: 1, environment: 'local-baseline', comparison: '' })
const selectedTargetType = ref('interview')
const selectedExperimentTargets = ref([])

const published = computed(() => releases.value.filter(release => release.status === 'published'))
const targets = computed(() => published.value.filter(release => release.release_type === 'target'))
const evaluations = computed(() => published.value.filter(release => (
  release.release_type === 'evaluation'
  && (!selectedTargetType.value || !release.target_type || release.target_type === selectedTargetType.value)
)))
const selectedEvaluation = computed(() => releases.value.find(release => String(release.id) === String(form.value.evaluation)))
const selectedCapability = computed(() => capabilities.value.find(item => (
  item.target_type === selectedTargetType.value
  && String(item.evaluation_release?.id || '') === String(form.value.evaluation)
)))
const runnableCapabilities = computed(() => capabilities.value.filter(item => item.can_run))

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
    structured: Boolean(manifest.structured_evaluation),
    resume: Boolean(manifest.resume_evaluation),
    tagging: Boolean(manifest.tagging_evaluation),
    caseCount: selectedCapability.value?.case_count || manifest.benchmark?.cases?.length || 0,
  }
})

const executionEstimate = computed(() => {
  const caseCount = evaluationConfig.value.caseCount || 0
  const replication = Number(form.value.replication) || 1
  const total = Math.max(0, caseCount * replication)
  const judgeCalls = Math.max(0, caseCount) * Math.max(0, Math.min(replication, 3))
  let estimate = total ? `${total} 次 E2E 执行` : '—'
  if (judgeCalls) estimate += `（约 ${judgeCalls} 次 Judge 调用）`
  return { total, judgeCalls, text: estimate }
})

function smokeCaseKey() {
  const evId = String(form.value.evaluation)
  const suite = benchmarks.value.find(s => String(s.evaluation_release_key || s.release_key) === evId || s.id === Number(evId))
  return suite?.cases?.[0]?.case_key || ''
}

async function submitSmoke() {
  if (!form.value.target || !form.value.evaluation) {
    error.value = '请选择被测版本和完整评测版本。'
    return
  }
  const caseKey = smokeCaseKey()
  if (!caseKey) {
    error.value = '没有找到 Benchmark Case，无法执行 Smoke。'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const result = await createEvaluationRun({
      target_release_id: Number(form.value.target),
      evaluation_release_id: Number(form.value.evaluation),
      replication_count: 1,
      seed: Number(form.value.seed),
      environment_fingerprint: form.value.environment,
      comparison_group: form.value.comparison,
      case_keys: [caseKey],
    })
    if (result?.dispatch_error) error.value = `入队异常：${result.dispatch_error}（Run 保持可重试状态）`
    router.push(`/admin/evals/runs/${result.run_id}`)
  } catch (err) {
    error.value = err.message || 'Smoke 评测失败'
  } finally {
    submitting.value = false
  }
}

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
    const [releaseData, runData, capabilityData, experimentData, benchmarkData] = await Promise.all([
      fetchEvaluationReleases(),
      fetchEvaluationRuns(),
      fetchEvaluationCapabilities(),
      fetchEvaluationExperiments(),
      fetchEvaluationBenchmarks(),
    ])
    releases.value = releaseData.releases || []
    runs.value = runData.runs || []
    capabilities.value = capabilityData.targets || []
    experiments.value = experimentData.experiments || []
    benchmarks.value = benchmarkData.suites || []
    selectedExperimentTargets.value = runnableCapabilities.value.map(item => item.target_type)
    chooseDefaults()
  } catch (err) {
    error.value = err.message || '评测实验加载失败'
  } finally {
    loading.value = false
  }
}

function toggleExperimentTarget(targetType) {
  if (selectedExperimentTargets.value.includes(targetType)) {
    selectedExperimentTargets.value = selectedExperimentTargets.value.filter(item => item !== targetType)
  } else {
    selectedExperimentTargets.value = [...selectedExperimentTargets.value, targetType]
  }
}

async function submitExperiment(targetTypes = selectedExperimentTargets.value) {
  if (!targetTypes.length) {
    error.value = '请至少选择一个可以运行的 Eval。'
    return
  }
  experimentSubmitting.value = true
  error.value = ''
  try {
    const result = await createEvaluationExperiment({
      target_types: targetTypes,
      replication_count: Number(form.value.replication),
      seed: Number(form.value.seed),
      environment_fingerprint: form.value.environment,
      comparison_group: form.value.comparison,
    })
    router.push({ path: `/admin/evals/experiments/${result.experiment_id}`, query: route.query.preview === '1' ? { preview: '1' } : {} })
  } catch (err) {
    error.value = err.message || '创建评测实验失败'
  } finally {
    experimentSubmitting.value = false
  }
}

function submitAllExperiments() {
  const allTargets = runnableCapabilities.value.map(item => item.target_type)
  selectedExperimentTargets.value = allTargets
  submitExperiment(allTargets)
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
            <EvaluationTargetPicker :model-value="selectedTargetType" :capabilities="capabilities" @update:model-value="selectTargetType" />
            <EvaluationStepCard :number="1" title="选择被测版本" description="决定这次要测哪个 Agent、Workflow 或 Pipeline。">
              <label class="block text-sm font-medium" for="eval-target">被测版本（{{ evaluationTargetLabel(selectedTargetType) }}）</label>
              <Select v-model="form.target" @update:model-value="selectTarget">
                <SelectTrigger class="mt-1.5">
                  <SelectValue placeholder="请选择被测版本" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="target in targets" :key="target" :value="String(target.id)">
                    {{ target.release_key }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <p class="mt-1.5 text-xs text-muted-foreground">每个 Agent / Workflow 独立建立自己的评测 Run，便于后续做 A/B。</p>
            </EvaluationStepCard>

            <EvaluationStepCard :number="2" title="选择完整评测版本" description="这一个版本整体固定 Benchmark、Judge、模拟器、Harness，以及工具调用和意图识别指标。">
              <label class="block text-sm font-medium" for="eval-release">完整评测版本</label>
              <Select v-model="form.evaluation">
                <SelectTrigger class="mt-1.5">
                  <SelectValue placeholder="请选择完整评测版本" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="release in evaluations" :key="release.id" :value="String(release.id)">
                    {{ release.release_key }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <div class="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">评测题集</span><div class="mt-1 font-medium">{{ evaluationConfig.benchmark }} · {{ evaluationConfig.caseCount }} 个 Case</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">固定 Judge</span><div class="mt-1 break-all font-mono font-medium">{{ evaluationConfig.judge }}</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">执行器 / 候选人</span><div class="mt-1 font-medium">{{ evaluationConfig.harness }} · {{ evaluationConfig.simulator === '—' ? '无需模拟器' : evaluationConfig.simulator }}</div></div>
                <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">明确指标</span><div class="mt-1 flex flex-wrap gap-1.5"><span v-if="evaluationConfig.tool" class="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 class="size-3.5" />工具调用效果</span><span v-if="evaluationConfig.intent" class="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 class="size-3.5" />意图识别效果</span><span v-if="evaluationConfig.structured" class="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 class="size-3.5" />字段与题目召回</span><span v-if="evaluationConfig.resume" class="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 class="size-3.5" />事实与岗位匹配</span><span v-if="evaluationConfig.tagging" class="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 class="size-3.5" />分类与标签准确率</span></div></div>
              </div>
            </EvaluationStepCard>

            <EvaluationStepCard :number="3" title="固定运行参数" description="这些参数会写入批次指纹，保证多次 E2E 可以复现和比较。">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="text-sm font-medium">每个 Case 重跑次数<Input v-model.number="form.replication" type="number" min="1" max="100" class="mt-1.5" /></label>
                <label class="text-sm font-medium">随机种子<Input v-model.number="form.seed" type="number" class="mt-1.5" /></label>
              </div>
              <label class="mt-3 block text-sm font-medium">运行环境标识<Input v-model="form.environment" class="mt-1.5" placeholder="local-baseline" /></label>
              <label class="mt-3 block text-sm font-medium">版本对比组（可选）<Input v-model="form.comparison" class="mt-1.5" placeholder="release-ab-2026-08" /></label>
              <p class="mt-1.5 text-xs text-muted-foreground">人工 A/B 必须使用同一完整评测版本、同一 Case 和同一输入快照，只改变被测版本。</p>
            </EvaluationStepCard>

            <div class="rounded-md bg-muted/40 p-3 text-xs text-muted-foreground">预计执行量：<span class="font-medium text-foreground">{{ executionEstimate.text }}</span><span v-if="executionEstimate.total" class="ml-1">· 完整评测耗时较长且消耗 Token，建议先用 Smoke 验证单 Case</span></div>
            <p v-if="error" class="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p>
            <div class="flex flex-wrap gap-2"><Button class="flex-1" type="submit" :disabled="submitting"><Play class="mr-1.5 size-4" />{{ submitting ? '正在创建...' : '创建并开始评测' }}</Button><Button type="button" variant="outline" :disabled="submitting || !executionEstimate.total" @click="submitSmoke"><Play class="mr-1.5 size-4" />执行 1 Case Smoke</Button></div>
          </form>
        </AppCard>

        <AppCard class="xl:col-span-2" title="批量评测实验" description="一次选择多个已接入 Agent，系统会为每个对象创建一个独立子 Run，并在 Experiment 页面汇总进度。">
          <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div>
              <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                <label v-for="capability in capabilities" :key="capability.target_type" class="flex cursor-pointer gap-3 rounded-lg border border-border/70 bg-background p-3 text-left has-[:checked]:border-primary has-[:checked]:bg-primary/5" :class="{ 'cursor-not-allowed opacity-60': !capability.can_run }">
                  <Checkbox 
                :checked="selectedExperimentTargets.includes(capability.target_type)" 
                :disabled="!capability.can_run" 
                @update:checked="toggleExperimentTarget(capability.target_type)"
              />
                  <span class="min-w-0"><span class="block text-sm font-medium">{{ evaluationTargetLabel(capability.target_type) }}</span><span class="mt-1 block text-xs text-muted-foreground">{{ capability.case_count || 0 }} 个 Case<span v-if="capability.reason"> · {{ capability.reason }}</span></span></span>
                </label>
              </div>
              <p v-if="!runnableCapabilities.length" class="mt-3 text-sm text-destructive">当前没有可运行的 Eval，请先完成版本发布和 Adapter 接入。</p>
              <p v-else class="mt-3 text-xs text-muted-foreground">已选 {{ selectedExperimentTargets.length }} / {{ runnableCapabilities.length }} 个 Eval；运行参数沿用左侧配置。</p>
            </div>
            <div class="flex flex-wrap gap-2 lg:justify-end">
              <Button variant="outline" :disabled="experimentSubmitting || !selectedExperimentTargets.length" @click="submitExperiment()"><Play class="mr-1.5 size-4" />{{ experimentSubmitting ? '正在创建...' : '运行选中的 Eval' }}</Button>
              <Button :disabled="experimentSubmitting || !runnableCapabilities.length" @click="submitAllExperiments"><Play class="mr-1.5 size-4" />运行全部 Eval</Button>
            </div>
          </div>
        </AppCard>

        <AppCard title="历史评测" description="选择一条记录查看实时进度、逐 Case 证据和最终聚合结果。" no-padding>
          <div class="flex items-center justify-end border-b border-border/60 p-3"><Button size="sm" variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button></div>
          <div v-if="!runs.length" class="p-8 text-center text-sm text-muted-foreground">还没有评测记录。</div>
          <div v-else class="divide-y divide-border/60">
            <Button v-for="run in runs" :key="run.id" variant="ghost" class="flex w-full items-center gap-4 p-4 text-left hover:bg-muted/40" @click="router.push(`/admin/evals/runs/${run.id}`)">
              <div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="font-medium">评测 #{{ run.id }}</span><span class="text-[11px] text-muted-foreground">执行</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span class="text-[11px] text-muted-foreground">质量</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.quality_status)]">{{ qualityStatusLabel(run.quality_status) }}</span><span v-if="run.comparison_group" class="text-xs text-muted-foreground">对比组：{{ run.comparison_group }}</span></div><div class="mt-1 text-xs text-muted-foreground">被测：{{ run.target_release_key }} · 评测：{{ run.evaluation_release_key || '历史组件模式' }} · {{ formatDate(run.created_at) }}</div></div>
              <div class="w-36"><div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span>{{ runProgress(run) }}%</span></div><div class="h-1.5 rounded-full bg-muted"><EvalProgressBar :value="runProgress(run)" size="sm" /></div></div>
            </button>
          </div>
        </AppCard>
      </div>
        <AppCard title="批量实验历史" description="查看一键启动的 Experiment 汇总进度，可进入任意子 Run 查看证据。" no-padding>
          <div class="flex items-center justify-end border-b border-border/60 p-3"><Button size="sm" variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button></div>
          <div v-if="!experiments.length" class="p-8 text-center text-sm text-muted-foreground">还没有批量实验记录。</div>
          <div v-else class="divide-y divide-border/60">
            <button v-for="experiment in experiments.slice(0, 10)" :key="experiment.id" type="button" class="flex w-full items-center gap-4 p-4 text-left hover:bg-muted/40" @click="router.push(`/admin/evals/experiments/${experiment.id}`)">
              <div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="font-medium">实验 #{{ experiment.id }}</span><span class="text-[11px] text-muted-foreground">执行</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(experiment.status)]">{{ statusLabel(experiment.status) }}</span><span class="text-[11px] text-muted-foreground">质量</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(experiment.quality_status)]">{{ qualityStatusLabel(experiment.quality_status) }}</span></div><div class="mt-1 text-xs text-muted-foreground">{{ experiment.total_runs }} 个子 Run · {{ (experiment.completed_runs || 0) + (experiment.failed_runs || 0) + (experiment.cancelled_runs || 0) }}/{{ experiment.total_runs }} 已完成 · {{ formatDate(experiment.created_at) }}</div></div>
              <ArrowRight class="size-4 shrink-0 text-muted-foreground" />
            </button>
          </div>
        </AppCard>

    </div>
  </div>
</template>
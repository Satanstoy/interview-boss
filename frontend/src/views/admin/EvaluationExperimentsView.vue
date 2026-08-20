<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CheckCircle2, Eye, Play, RefreshCw, XCircle } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cancelEvaluationExperiment, createEvaluationExperiment, createEvaluationRun, fetchEvaluationBenchmarks, fetchEvaluationCapabilities, fetchEvaluationExperiments, fetchEvaluationReleases, fetchProjectHarnessReleases } from '@/services/evaluationApi.js'
import { evaluationTargetLabel, formatDate, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import EvaluationStepCard from './EvaluationStepCard.vue'
import EvaluationTargetPicker from './EvaluationTargetPicker.vue'

const router = useRouter()
const route = useRoute()
const releases = ref([])
const capabilities = ref([])
const benchmarks = ref([])
const harnesses = ref([])
const loading = ref(true)
const submitting = ref(false)
const experimentSubmitting = ref(false)
const experimentsLoading = ref(false)
const experiments = ref([])
const activeTab = ref(route.query.tab === 'create' ? 'create' : 'active')
const selectedExperimentId = ref(null)
const cancellingExperimentId = ref(null)
const error = ref('')
const form = ref({ target: '', evaluation: '', harness: '', replication: 5, seed: 1, environment: 'local-baseline', comparison: '' })
const selectedTargetType = ref('interview')
const selectedExperimentTargets = ref([])
let experimentPollTimer = null
let experimentsRequestInFlight = false
let componentActive = false

const activeExperiments = computed(() => experiments.value.filter(experiment => ['created', 'queued', 'running'].includes(experiment.status)))

function experimentProgress(experiment) {
  if (experiment?.total_items) {
    return Math.round((((experiment.completed_items || 0) + (experiment.failed_items || 0)) / experiment.total_items) * 100)
  }
  if (experiment?.total_runs) {
    return Math.round((((experiment.completed_runs || 0) + (experiment.failed_runs || 0) + (experiment.cancelled_runs || 0)) / experiment.total_runs) * 100)
  }
  return 0
}

function experimentTargets(experiment) {
  const labels = [...new Set((experiment?.runs || []).map(run => evaluationTargetLabel(run.target_type)))]
  return labels.length ? labels.join('、') : '—'
}

function experimentHarness(experiment) {
  const versions = (experiment?.runs || [])
    .filter(run => run.project_harness_key && run.project_harness_version)
    .map(run => `${run.project_harness_key}@${run.project_harness_version}`)
  return [...new Set(versions)].join('、') || '—'
}

function experimentEvaluation(experiment) {
  const versions = (experiment?.runs || [])
    .map(run => run.benchmark_suite_release_key || run.evaluation_release_key)
    .filter(Boolean)
  return [...new Set(versions)].join('、') || '—'
}

function capabilityVersionOverrides(targetTypes) {
  const targetReleaseIds = {}
  const evaluationReleaseIds = {}
  const projectHarnessReleaseIds = {}
  targetTypes.forEach(targetType => {
    const capability = capabilities.value.find(item => item.target_type === targetType)
    if (capability?.target_release?.id) targetReleaseIds[targetType] = capability.target_release.id
    if (capability?.evaluation_release?.id) evaluationReleaseIds[targetType] = capability.evaluation_release.id
    if (capability?.project_harness?.id) projectHarnessReleaseIds[targetType] = capability.project_harness.id
  })
  return {
    target_release_ids: targetReleaseIds,
    evaluation_release_ids: evaluationReleaseIds,
    project_harness_release_ids: projectHarnessReleaseIds,
  }
}

async function loadExperiments() {
  if (!componentActive || experimentsRequestInFlight) return
  experimentsRequestInFlight = true
  experimentsLoading.value = true
  error.value = ''
  try {
    const data = await fetchEvaluationExperiments()
    experiments.value = data.experiments || []
    if (selectedExperimentId.value && !activeExperiments.value.some(item => item.id === selectedExperimentId.value)) {
      selectedExperimentId.value = null
    }
  } catch (err) {
    if (!error.value) error.value = err.message || '进行中的测评加载失败'
  } finally {
    experimentsLoading.value = false
    experimentsRequestInFlight = false
  }
}

function selectTab(tab) {
  activeTab.value = tab
  if (tab === 'active') loadExperiments()
}

function openExperiment(experiment) {
  router.push({
    path: `/admin/evals/experiments/${experiment.id}`,
    query: route.query.preview === '1' ? { preview: '1' } : {},
  })
}

async function cancelExperiment(experiment) {
  cancellingExperimentId.value = experiment.id
  error.value = ''
  try {
    await cancelEvaluationExperiment(experiment.id)
    await loadExperiments()
  } catch (err) {
    error.value = err.message || '取消测评失败'
  } finally {
    cancellingExperimentId.value = null
  }
}

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
const availableHarnesses = computed(() => harnesses.value.filter(harness => (
  harness.status === 'published' && harness.target_type === selectedTargetType.value
)))
const selectedHarness = computed(() => availableHarnesses.value.find(harness => String(harness.id) === String(form.value.harness)))

function manifestOf(release) {
  if (release?.manifest && typeof release.manifest === 'object') return release.manifest
  try { return JSON.parse(release?.manifest_json || '{}') } catch { return {} }
}

const evaluationConfig = computed(() => {
  const manifest = manifestOf(selectedEvaluation.value)
  return {
    benchmark: manifest.benchmark?.suite_key || '—',
    judge: manifest.judge?.model || selectedEvaluation.value?.judge_model || '—',
    harness: selectedHarness.value ? `${selectedHarness.value.harness_key}@${selectedHarness.value.version}` : (selectedEvaluation.value?.project_harness_release_key || '未记录'),
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
  if (judgeCalls) estimate += `（约 ${judgeCalls} 次质量评审）`
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
    error.value = '没有找到评测集 Case，无法执行单 Case 评测。'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const result = await createEvaluationRun({
      target_release_id: Number(form.value.target),
      evaluation_release_id: Number(form.value.evaluation),
      project_harness_release_id: form.value.harness ? Number(form.value.harness) : undefined,
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
  syncHarnessSelection()
}

function syncHarnessSelection() {
  const currentId = selectedCapability.value?.project_harness?.id
  if (currentId && availableHarnesses.value.some(harness => String(harness.id) === String(currentId))) {
    form.value.harness = String(currentId)
    return
  }
  if (!availableHarnesses.value.some(harness => String(harness.id) === String(form.value.harness))) {
    form.value.harness = availableHarnesses.value[0] ? String(availableHarnesses.value[0].id) : ''
  }
}

function selectTargetType(type) {
  selectedTargetType.value = type
  const target = targets.value.find(release => release.target_type === type)
  if (target) form.value.target = String(target.id)
  const evaluation = evaluations.value.find(release => release.target_type === type) || evaluations.value[0]
  form.value.evaluation = evaluation ? String(evaluation.id) : ''
  syncHarnessSelection()
}

function selectTarget() {
  const target = targets.value.find(release => String(release.id) === String(form.value.target))
  selectedTargetType.value = target?.target_type || ''
  const evaluation = evaluations.value.find(release => String(release.id) === String(form.value.evaluation)) || evaluations.value[0]
  form.value.evaluation = evaluation ? String(evaluation.id) : ''
  syncHarnessSelection()
}

async function load() {
  loading.value = true
  error.value = ''
  experimentsRequestInFlight = true
  try {
    const [releaseData, capabilityData, benchmarkData, harnessData, experimentData] = await Promise.all([
      fetchEvaluationReleases(),
      fetchEvaluationCapabilities(),
      fetchEvaluationBenchmarks(),
      fetchProjectHarnessReleases(),
      fetchEvaluationExperiments(),
    ])
    releases.value = releaseData.releases || []
    capabilities.value = capabilityData.targets || []
    benchmarks.value = benchmarkData.suites || []
    harnesses.value = harnessData.harness_releases || []
    experiments.value = experimentData.experiments || []
    selectedExperimentTargets.value = runnableCapabilities.value.map(item => item.target_type)
    chooseDefaults()
  } catch (err) {
    error.value = err.message || '评测实验加载失败'
  } finally {
    loading.value = false
    experimentsRequestInFlight = false
  }
}

function toggleExperimentTarget(targetType) {
  if (selectedExperimentTargets.value.includes(targetType)) {
    selectedExperimentTargets.value = selectedExperimentTargets.value.filter(item => item !== targetType)
  } else {
    selectedExperimentTargets.value = [...selectedExperimentTargets.value, targetType]
  }
}

async function submitExperiment(targetTypes = selectedExperimentTargets.value, versionOverrides = capabilityVersionOverrides(targetTypes)) {
  if (!targetTypes.length) {
    error.value = '请至少选择一个可以运行的 Eval。'
    return
  }
  experimentSubmitting.value = true
  error.value = ''
  try {
    const result = await createEvaluationExperiment({
      target_types: targetTypes,
      ...versionOverrides,
      replication_count: Number(form.value.replication),
      seed: Number(form.value.seed),
      environment_fingerprint: form.value.environment,
      comparison_group: form.value.comparison,
    })
    selectedExperimentId.value = result.experiment_id
    await loadExperiments()
    activeTab.value = 'active'
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
  await submitExperiment([selectedTargetType.value], {
    target_release_ids: { [selectedTargetType.value]: Number(form.value.target) },
    evaluation_release_ids: { [selectedTargetType.value]: Number(form.value.evaluation) },
    project_harness_release_ids: form.value.harness
      ? { [selectedTargetType.value]: Number(form.value.harness) }
      : {},
  })
}

onMounted(() => {
  componentActive = true
  load()
  experimentPollTimer = window.setInterval(() => {
    if (activeTab.value === 'active') loadExperiments()
  }, 5000)
})

onUnmounted(() => {
  componentActive = false
  if (experimentPollTimer) window.clearInterval(experimentPollTimer)
})
</script>

<template>
  <div class="h-full min-h-0 overflow-hidden custom-scrollbar" data-evaluation-workbench>
    <div class="mx-auto flex h-full min-h-0 max-w-7xl flex-col px-4 py-5 sm:px-6 lg:px-8">
      <EvaluationPageHeader title="测评实验" description="管理正在运行的测评实验，或创建一次固定版本、固定参数的评测。" active-key="experiments">
        <template #actions>
          <Button v-if="activeTab === 'active'" @click="selectTab('create')"><Play class="mr-1.5 size-4" />创建测评</Button>
          <Button v-else variant="outline" @click="selectTab('active')"><Eye class="mr-1.5 size-4" />查看进行中</Button>
        </template>
      </EvaluationPageHeader>

      <div class="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border/70 bg-background shadow-sm">
        <div role="tablist" aria-label="测评实验工作区" class="flex shrink-0 items-center gap-1 border-b border-border/70 px-3 pt-2 sm:px-5">
          <button role="tab" type="button" :aria-selected="activeTab === 'active'" :class="['inline-flex items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium transition-colors', activeTab === 'active' ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground']" @click="selectTab('active')">
            进行中的测评
            <Badge variant="secondary">{{ activeExperiments.length }}</Badge>
          </button>
          <button role="tab" type="button" :aria-selected="activeTab === 'create'" :class="['inline-flex items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium transition-colors', activeTab === 'create' ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground']" @click="selectTab('create')">
            创建测评
          </button>
        </div>

        <div v-if="loading" class="flex min-h-64 flex-1 items-center justify-center"><AsyncLoading /></div>

        <div v-else-if="activeTab === 'active'" class="min-h-0 flex-1 overflow-y-auto p-4 custom-scrollbar sm:p-5">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 class="text-base font-semibold">进行中的测评</h2>
              <p class="mt-1 text-xs text-muted-foreground">排队中和执行中的实验会自动刷新；已完成的实验请到「评测结果」查看。</p>
            </div>
            <Button variant="outline" size="sm" :disabled="experimentsLoading" @click="loadExperiments"><RefreshCw :class="['mr-1.5 size-4', { 'animate-spin': experimentsLoading }]" />刷新</Button>
          </div>
          <p v-if="error" class="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p>

          <div v-if="experimentsLoading && !experiments.length" class="flex min-h-56 items-center justify-center"><AsyncLoading /></div>
          <div v-else-if="!activeExperiments.length" class="mt-5 flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-border/80 bg-muted/20 p-8 text-center">
            <h3 class="text-sm font-semibold">当前没有进行中的测评</h3>
            <p class="mt-1.5 max-w-md text-sm text-muted-foreground">创建一次测评后，这里会显示 Harness 版本、评测集版本和实时进度。</p>
            <Button class="mt-4" @click="selectTab('create')"><Play class="mr-1.5 size-4" />创建测评</Button>
          </div>
          <div v-else class="mt-5 overflow-x-auto rounded-xl border border-border/70">
            <table class="w-full min-w-[960px] text-left text-sm">
              <thead class="bg-muted/35 text-xs text-muted-foreground">
                <tr>
                  <th class="px-4 py-3 font-medium">实验</th>
                  <th class="px-4 py-3 font-medium">测评对象</th>
                  <th class="px-4 py-3 font-medium">Harness 版本</th>
                  <th class="px-4 py-3 font-medium">评测集版本</th>
                  <th class="px-4 py-3 font-medium">状态</th>
                  <th class="px-4 py-3 font-medium">进度</th>
                  <th class="px-4 py-3 font-medium">创建时间</th>
                  <th class="px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border/60">
                <tr v-for="experiment in activeExperiments" :key="experiment.id" :data-testid="`active-experiment-row-${experiment.id}`" :class="['align-top transition-colors hover:bg-muted/25', selectedExperimentId === experiment.id ? 'bg-primary/5' : '']">
                  <td class="px-4 py-4">
                    <button type="button" class="text-left font-medium text-foreground hover:text-primary" @click="openExperiment(experiment)">
                      实验 #{{ experiment.id }}
                      <span class="mt-1 block max-w-[170px] truncate text-xs font-normal text-muted-foreground">{{ experiment.experiment_key || '未命名实验' }}</span>
                    </button>
                  </td>
                  <td class="max-w-[180px] px-4 py-4 text-xs leading-5">{{ experimentTargets(experiment) }}</td>
                  <td class="px-4 py-4 font-mono text-xs">{{ experimentHarness(experiment) }}</td>
                  <td class="px-4 py-4 font-mono text-xs">{{ experimentEvaluation(experiment) }}</td>
                  <td class="px-4 py-4"><Badge :class="statusClass(experiment.status)">{{ statusLabel(experiment.status) }}</Badge></td>
                  <td class="w-44 px-4 py-4">
                    <div class="flex items-center justify-between gap-2 text-xs"><span class="font-medium">{{ experimentProgress(experiment) }}%</span><span class="text-muted-foreground">{{ experiment.completed_items || 0 }} / {{ experiment.total_items || 0 }} Cases</span></div>
                    <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all" :style="{ width: `${experimentProgress(experiment)}%` }" /></div>
                    <div class="mt-1 text-[11px] text-muted-foreground">{{ experiment.failed_items || 0 }} 失败</div>
                  </td>
                  <td class="whitespace-nowrap px-4 py-4 text-xs text-muted-foreground">{{ formatDate(experiment.created_at) }}</td>
                  <td class="px-4 py-4">
                    <div class="flex items-center gap-2">
                      <Button size="sm" variant="outline" @click="openExperiment(experiment)"><Eye class="mr-1.5 size-3.5" />详情</Button>
                      <Button size="sm" variant="ghost" class="text-destructive hover:text-destructive" :disabled="cancellingExperimentId === experiment.id" @click.stop="cancelExperiment(experiment)"><XCircle class="mr-1.5 size-3.5" />{{ cancellingExperimentId === experiment.id ? '取消中' : '取消' }}</Button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else class="min-h-0 flex-1 overflow-y-auto p-4 custom-scrollbar sm:p-5">
          <div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
            <AppCard title="创建一次测评" description="固定被测版本、Harness、评测集和运行参数后，再开始执行。">
              <form class="space-y-3" @submit.prevent="submit">
                <EvaluationTargetPicker :model-value="selectedTargetType" :capabilities="capabilities" @update:model-value="selectTargetType" />
                <EvaluationStepCard :number="1" title="选择被测版本" description="决定这次要测哪个 Agent、Workflow 或 Pipeline。">
                  <label class="block text-sm font-medium" for="eval-target">被测版本（{{ evaluationTargetLabel(selectedTargetType) }}）</label>
                  <Select v-model="form.target" @update:model-value="selectTarget">
                    <SelectTrigger class="mt-1.5"><SelectValue placeholder="请选择被测版本" /></SelectTrigger>
                    <SelectContent><SelectItem v-for="target in targets" :key="target.id" :value="String(target.id)">{{ target.release_key }}</SelectItem></SelectContent>
                  </Select>
                  <p class="mt-1.5 text-xs text-muted-foreground">每个 Agent / Workflow 独立建立自己的评测 Run，便于后续做 A/B。</p>
                </EvaluationStepCard>

                <EvaluationStepCard :number="2" title="选择评测配置" description="固定评测集、评分模型、Harness 和本次要看的业务指标。">
                  <label class="block text-sm font-medium" for="eval-release">完整评测版本</label>
                  <Select v-model="form.evaluation">
                    <SelectTrigger class="mt-1.5"><SelectValue placeholder="请选择完整评测版本" /></SelectTrigger>
                    <SelectContent><SelectItem v-for="release in evaluations" :key="release.id" :value="String(release.id)">{{ release.release_key }}</SelectItem></SelectContent>
                  </Select>
                  <label class="mt-3 block text-sm font-medium">被测 Harness 版本</label>
                  <Select v-model="form.harness">
                    <SelectTrigger class="mt-1.5"><SelectValue placeholder="请选择 Harness 版本" /></SelectTrigger>
                    <SelectContent><SelectItem v-for="harness in availableHarnesses" :key="harness.id" :value="String(harness.id)">{{ harness.harness_key }}@{{ harness.version }}</SelectItem></SelectContent>
                  </Select>
                  <p class="mt-1.5 text-xs text-muted-foreground">A/B 时固定同一评测集，只切换这里的 Harness 版本。</p>
                  <div class="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                    <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">评测题集</span><div class="mt-1 font-medium">{{ evaluationConfig.benchmark }} · {{ evaluationConfig.caseCount }} 个 Case</div></div>
                    <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">评分模型</span><div class="mt-1 break-all font-mono font-medium">{{ evaluationConfig.judge }}</div></div>
                    <div class="rounded-lg bg-muted/40 p-3"><span class="text-muted-foreground">Harness / 模拟人</span><div class="mt-1 font-medium">{{ evaluationConfig.harness }} · {{ evaluationConfig.simulator === '—' ? '无需模拟人' : evaluationConfig.simulator }}</div></div>
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
                  <p class="mt-1.5 text-xs text-muted-foreground">人工 A/B 必须使用同一完整评测版本、同一 Case、同一输入快照和同一随机种子，只改变 Harness 版本。</p>
                </EvaluationStepCard>

                <p v-if="error" class="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p>
                <div class="sticky bottom-0 -mx-4 border-t border-border/70 bg-background/95 px-4 pb-1 pt-4 backdrop-blur sm:-mx-5 sm:px-5">
                  <div class="flex flex-wrap gap-2"><Button class="flex-1" type="submit" :disabled="submitting || experimentSubmitting"><Play class="mr-1.5 size-4" />{{ experimentSubmitting ? '正在创建...' : '创建并开始测评' }}</Button><Button type="button" variant="outline" :disabled="submitting || experimentSubmitting || !executionEstimate.total" @click="submitSmoke"><Play class="mr-1.5 size-4" />执行 1 Case Smoke</Button></div>
                </div>
              </form>
            </AppCard>

            <aside class="space-y-5 lg:sticky lg:top-0 lg:self-start">
              <AppCard title="批量运行" description="一次选择多个测评对象，系统会分别建立 Run 并汇总进度。">
                <div class="space-y-3">
                  <label v-for="capability in capabilities" :key="capability.target_type" :class="['flex cursor-pointer gap-3 rounded-lg border p-3 text-left', selectedExperimentTargets.includes(capability.target_type) ? 'border-primary bg-primary/5 ring-1 ring-primary/30' : 'border-border/70 bg-background has-[:checked]:border-primary has-[:checked]:bg-primary/5', { 'cursor-not-allowed opacity-60': !capability.can_run }]">
                    <Checkbox :checked="selectedExperimentTargets.includes(capability.target_type)" :disabled="!capability.can_run" @update:checked="toggleExperimentTarget(capability.target_type)" />
                    <span class="min-w-0"><span class="block text-sm font-medium">{{ evaluationTargetLabel(capability.target_type) }}</span><span class="mt-1 block text-xs text-muted-foreground">{{ capability.case_count || 0 }} 个 Case<span v-if="capability.reason"> · {{ capability.reason }}</span></span><span v-if="capability.can_run && capability.project_harness && capability.evaluation_release" class="mt-1 block truncate text-[11px] text-muted-foreground">{{ capability.project_harness.harness_key }}@{{ capability.project_harness.version }} · {{ capability.evaluation_release.release_key }}</span></span>
                  </label>
                  <p v-if="!runnableCapabilities.length" class="text-sm text-destructive">当前没有可运行的 Eval，请先完成版本发布和 Adapter 接入。</p>
                  <p v-else class="text-xs text-muted-foreground">已选 {{ selectedExperimentTargets.length }} / {{ runnableCapabilities.length }} 个测评对象。</p>
                  <div class="flex flex-wrap gap-2"><Button class="flex-1" variant="outline" :disabled="experimentSubmitting || !selectedExperimentTargets.length" @click="submitExperiment()"><Play class="mr-1.5 size-4" />{{ experimentSubmitting ? '正在创建...' : '运行选中的 Eval' }}</Button><Button class="flex-1" :disabled="experimentSubmitting || !runnableCapabilities.length" @click="submitAllExperiments"><Play class="mr-1.5 size-4" />运行全部 Eval</Button></div>
                </div>
              </AppCard>

              <AppCard title="本次固定范围" description="开始后，这些版本和参数会随实验保存，后续不会被实时配置覆盖。">
                <dl class="space-y-3 text-xs">
                  <div class="flex items-start justify-between gap-3"><dt class="text-muted-foreground">Harness</dt><dd class="break-all text-right font-mono font-medium">{{ evaluationConfig.harness }}</dd></div>
                  <div class="flex items-start justify-between gap-3"><dt class="text-muted-foreground">评测题集</dt><dd class="text-right font-medium">{{ evaluationConfig.benchmark }} · {{ evaluationConfig.caseCount }} Cases</dd></div>
                  <div class="flex items-start justify-between gap-3"><dt class="text-muted-foreground">运行量</dt><dd class="text-right font-medium">{{ executionEstimate.text }}</dd></div>
                  <div class="flex items-start justify-between gap-3"><dt class="text-muted-foreground">环境</dt><dd class="break-all text-right font-mono font-medium">{{ form.environment || '—' }}</dd></div>
                </dl>
                <p class="mt-4 rounded-lg bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">完整测评耗时较长且消耗 Token，建议先用 Smoke 验证单 Case。</p>
              </AppCard>
            </aside>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

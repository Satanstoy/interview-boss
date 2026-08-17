<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeftRight, Check, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createHumanReview, fetchEvaluationRun, fetchEvaluationRuns, fetchHumanReviews } from '@/services/evaluationApi.js'
import { formatDate, reviewChoiceLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const runs = ref([])
const reviews = ref([])
const runA = ref(null)
const runB = ref(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const form = ref({ group: '', runA: '', runB: '', item: '', choice: '', comment: '', dimensions: '{}' })

const groups = computed(() => [...new Set(runs.value.map(run => run.comparison_group).filter(Boolean))])
const groupRuns = computed(() => runs.value.filter(run => !form.value.group || run.comparison_group === form.value.group))
const itemKeys = computed(() => {
  const keys = runA.value?.items?.map(item => `${item.case_key}#${item.replication_index}`) || []
  const bKeys = new Set(runB.value?.items?.map(item => `${item.case_key}#${item.replication_index}`) || [])
  return keys.filter(key => bKeys.has(key))
})
const itemA = computed(() => runA.value?.items?.find(item => `${item.case_key}#${item.replication_index}` === form.value.item))
const itemB = computed(() => runB.value?.items?.find(item => `${item.case_key}#${item.replication_index}` === form.value.item))
const turns = item => item?.result?.observation?.payload?.turns || []
const reviewStep = computed(() => {
  if (!form.value.group) return 1
  if (!runA.value || !runB.value) return 2
  if (!form.value.item) return 3
  if (!form.value.choice) return 4
  return 5
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [runData, reviewData] = await Promise.all([fetchEvaluationRuns(), fetchHumanReviews()])
    runs.value = runData.runs || []
    reviews.value = reviewData.reviews || []
    if (!form.value.group) form.value.group = groups.value[0] || ''
  } catch (err) {
    error.value = err.message || '人工评测加载失败'
  } finally {
    loading.value = false
  }
}

async function loadRun(which, id) {
  if (!id) {
    if (which === 'a') runA.value = null
    else runB.value = null
    return
  }
  try {
    const data = await fetchEvaluationRun(id)
    if (which === 'a') runA.value = data
    else runB.value = data
  } catch (err) {
    error.value = err.message || 'Run 详情加载失败'
  }
}

async function save() {
  if (!form.value.group || !form.value.item || !form.value.choice || !runA.value || !runB.value) {
    error.value = '请先完成比较组、两条 Run、Case 和 A/B 选择'
    return
  }
  saving.value = true
  error.value = ''
  try {
    let dimensions = {}
    try {
      dimensions = JSON.parse(form.value.dimensions || '{}')
    } catch {
      throw new Error('维度 JSON 格式不正确')
    }
    await createHumanReview({ comparison_group: form.value.group, run_a_id: runA.value.id, run_b_id: runB.value.id, item_key: form.value.item, choice: form.value.choice, dimensions, comment: form.value.comment })
    form.value.comment = ''
    form.value.choice = ''
    await load()
  } catch (err) {
    error.value = err.message || '保存人工评测失败'
  } finally {
    saving.value = false
  }
}

watch(() => form.value.group, () => {
  form.value.runA = ''
  form.value.runB = ''
  form.value.item = ''
  form.value.choice = ''
  runA.value = null
  runB.value = null
})

onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader title="人工 A/B：核对版本差异" description="在相同输入、Benchmark、Harness、Simulator 和 Judge 下，逐 Case 比较两个版本的完整回答。" active-key="reviews" />
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <template v-else>
        <AppCard class="mt-6" title="人工比较工作台" description="先定位同一 Case，再阅读两边的完整 E2E 回答，最后记录你的判断。">
          <div class="mb-5 grid gap-2 sm:grid-cols-4">
            <div v-for="step in [{ number: 1, label: '选择比较组' }, { number: 2, label: '选择两个版本' }, { number: 3, label: '选择 Case' }, { number: 4, label: '提交判断' }]" :key="step.number" :class="['flex items-center gap-2 rounded-lg border px-3 py-2 text-xs', reviewStep >= step.number ? 'border-primary/30 bg-primary/5 text-primary' : 'border-border/70 text-muted-foreground']"><span class="flex size-5 items-center justify-center rounded-full bg-background font-semibold ring-1 ring-border/70">{{ step.number }}</span>{{ step.label }}</div>
          </div>

          <div v-if="!groups.length" class="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-10 text-center"><div class="font-medium">还没有可比较的对比组</div><p class="mt-1 text-sm text-muted-foreground">创建评测时填写相同的版本对比组，完成两条 Run 后就能在这里进行人工 A/B。</p></div>
          <template v-else>
            <div class="grid gap-4 md:grid-cols-4">
              <label class="text-sm font-medium">第 1 步：比较组<select v-model="form.group" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"><option value="">请选择</option><option v-for="group in groups" :key="group" :value="group">{{ group }}</option></select></label>
              <label class="text-sm font-medium">第 2 步：版本 A<select v-model="form.runA" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" @change="loadRun('a', form.runA)"><option value="">请选择</option><option v-for="run in groupRuns" :key="run.id" :value="run.id">评测 #{{ run.id }} · {{ run.target_release_key }}</option></select></label>
              <label class="text-sm font-medium">版本 B<select v-model="form.runB" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" @change="loadRun('b', form.runB)"><option value="">请选择</option><option v-for="run in groupRuns" :key="run.id" :value="run.id">评测 #{{ run.id }} · {{ run.target_release_key }}</option></select></label>
              <label class="text-sm font-medium">第 3 步：Case<select v-model="form.item" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"><option value="">请选择</option><option v-for="key in itemKeys" :key="key" :value="key">{{ key }}</option></select></label>
            </div>

            <div class="mt-6 grid gap-5 lg:grid-cols-2">
              <article v-for="entry in [{ item: itemA, label: '回答 A', run: runA }, { item: itemB, label: '回答 B', run: runB }]" :key="entry.label" class="rounded-xl border border-border/70 bg-muted/20 p-4">
                <div class="mb-3 flex items-start gap-3"><div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-background text-primary ring-1 ring-border/70"><ArrowLeftRight class="size-4" /></div><div><h3 class="font-medium">{{ entry.label }}</h3><p class="mt-0.5 text-xs text-muted-foreground">{{ entry.run?.target_release_key || '选择版本后显示' }}</p></div></div>
                <div v-if="turns(entry.item).length" class="space-y-3 text-sm"><div v-for="turn in turns(entry.item)" :key="turn.turn" class="rounded-lg bg-background p-3"><div class="text-xs text-muted-foreground">第 {{ turn.turn }} 轮</div><div class="mt-2 text-xs text-muted-foreground">候选人：{{ turn.user }}</div><div class="mt-1 leading-6">面试官：{{ turn.assistant }}</div></div></div>
                <div v-else class="flex min-h-40 items-center justify-center text-center text-sm text-muted-foreground">选择两个版本和 Case 后显示完整回答。</div>
              </article>
            </div>

            <div class="mt-6 rounded-xl border border-primary/20 bg-primary/5 p-4">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between"><div><div class="text-sm font-semibold">第 4 步：你的判断</div><p class="mt-1 text-xs text-muted-foreground">只根据当前 Case 的回答质量做选择，不要把版本名称或分数当作答案提示。</p></div><div class="flex flex-wrap gap-2" role="radiogroup" aria-label="人工 A/B 选择"><button v-for="choice in [{ key: 'a', label: 'A 更好' }, { key: 'b', label: 'B 更好' }, { key: 'tie', label: '平局' }, { key: 'both_fail', label: '都失败' }]" :key="choice.key" type="button" :aria-pressed="form.choice === choice.key" :class="['rounded-md border px-3 py-2 text-sm transition-colors', form.choice === choice.key ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background hover:border-primary/50']" @click="form.choice = choice.key">{{ choice.label }}</button></div></div>
              <label class="mt-4 block text-sm font-medium">选择依据 <Input v-model="form.comment" class="mt-1.5 bg-background" placeholder="例如：A 的追问更贴近候选人回答，B 的收口更完整" /></label>
              <details class="mt-3 rounded-lg border border-border/60 bg-background/60 px-3 py-2"><summary class="cursor-pointer text-xs font-medium text-muted-foreground">高级：记录维度化 JSON</summary><textarea v-model="form.dimensions" class="mt-3 min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs" placeholder='{"flow":"a","evidence":"tie"}' /></details>
              <p v-if="error" class="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p>
              <div class="mt-4 flex justify-end"><Button :disabled="saving" @click="save"><Check class="mr-1.5 size-4" />{{ saving ? '保存中...' : '保存人工选择' }}</Button></div>
            </div>
          </template>
        </AppCard>

        <AppCard class="mt-6" title="已保存的人工评测" description="人工选择是独立证据，不会覆盖硬门禁或 LLM Judge 结果。" no-padding>
          <div class="flex justify-end border-b border-border/60 p-3"><Button size="sm" variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button></div>
          <div v-if="!reviews.length" class="p-8 text-center text-sm text-muted-foreground">还没有人工 A/B 记录。</div>
          <div v-else class="divide-y divide-border/60"><div v-for="review in reviews" :key="review.id" class="flex flex-wrap items-center gap-3 p-4 text-sm"><span class="font-medium">{{ review.comparison_group }}</span><span class="rounded-full bg-primary/10 px-2 py-0.5 text-primary">{{ reviewChoiceLabel(review.choice) }}</span><span class="text-muted-foreground">{{ review.item_key }}</span><span class="ml-auto text-xs text-muted-foreground">{{ formatDate(review.created_at) }}</span><span v-if="review.comment" class="basis-full text-muted-foreground">{{ review.comment }}</span></div></div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, ArrowLeftRight, ArrowRight, Check, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { createHumanReview, fetchEvaluationRun, fetchEvaluationRuns, fetchHumanReviews } from '@/services/evaluationApi.js'
import { formatDate, reviewChoiceLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import { Badge } from '@/components/ui/badge'

const runs = ref([])
const route = useRoute()
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
const hardAssertions = item => item?.result?.observation?.hard_assertions || []
const metrics = item => item?.result?.observation?.payload || {}
const reviewStep = computed(() => {
  if (!form.value.group) return 1
  if (!runA.value || !runB.value) return 2
  if (!form.value.item) return 3
  if (!form.value.choice) return 4
  return 5
})

// Progress: how many items have been reviewed
const reviewedKeys = computed(() => new Set(reviews.value.map(r => r.item_key)))
const reviewProgress = computed(() => {
  const total = itemKeys.value.length
  const reviewed = itemKeys.value.filter(k => reviewedKeys.value.has(k)).length
  return { total, reviewed }
})
const currentCaseIndex = computed(() => itemKeys.value.indexOf(form.value.item))

function navigateCase(direction) {
  const keys = itemKeys.value
  if (!keys.length) return
  const idx = currentCaseIndex.value
  const next = direction === 'next'
    ? Math.min(idx + 1, keys.length - 1)
    : Math.max(idx - 1, 0)
  if (next >= 0 && next < keys.length) form.value.item = keys[next];
}

function handleKeydown(e) {
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return
  if (e.key === '1') { form.value.choice = 'a' }
  else if (e.key === '2') { form.value.choice = 'b' }
  else if (e.key === '3') { form.value.choice = 'tie' }
  else if (e.key === '4') { form.value.choice = 'both_fail' }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); navigateCase('prev') }
  else if (e.key === 'ArrowRight') { e.preventDefault(); navigateCase('next') }
  else if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save() }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [runData, reviewData] = await Promise.all([fetchEvaluationRuns(), fetchHumanReviews()])
    runs.value = runData.runs || []
    reviews.value = reviewData.reviews || []
    if (!form.value.group) form.value.group = String(route.query.group || groups.value[0] || '')
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
    try { dimensions = JSON.parse(form.value.dimensions || '{}') } catch { throw new Error('维度 JSON 格式不正确') }
    await createHumanReview({ comparison_group: form.value.group, run_a_id: runA.value.id, run_b_id: runB.value.id, item_key: form.value.item, choice: form.value.choice, dimensions, comment: form.value.comment })
    form.value.comment = ''
    form.value.choice = ''
    // Auto-advance to next unreviewed case
    const nextUnreviewed = itemKeys.value.find(k => !reviewedKeys.value.has(k) && k !== form.value.item)
    if (nextUnreviewed) form.value.item = nextUnreviewed
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

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
  load()
})

onUnmounted(() => document.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header -->
    <div class="shrink-0 border-b border-border/60">
      <div class="mx-auto max-w-[1600px] px-4 py-3 sm:px-6 lg:px-8">
        <EvaluationPageHeader title="人工 A/B：核对版本差异" description="先定位同一个完整评测版本下的两条 Run，再阅读同一 Case 的完整 E2E 回答，最后记录你的判断。" active-key="reviews" />
      </div>
    </div>

    <div v-if="loading" class="flex flex-1 items-center justify-center"><AsyncLoading /></div>
    <template v-else>
      <!-- Step indicator + progress -->
      <div class="shrink-0 mx-auto w-full max-w-[1600px] px-4 pt-4 sm:px-6 lg:px-8">
        <div class="flex flex-wrap items-center gap-3 rounded-xl border border-border/70 bg-muted/20 px-4 py-2.5">
          <div aria-live="polite" v-for="step in [{ number: 1, label: '选择比较组' }, { number: 2, label: '选择两个版本' }, { number: 3, label: '选择 Case' }, { number: 4, label: '提交判断' }]" :key="step.number" :class="['flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs', reviewStep >= step.number ? 'border-primary/30 bg-primary/5 text-primary' : 'border-border/70 text-muted-foreground']"><span class="flex size-4 items-center justify-center rounded-full bg-background text-[10px] font-semibold ring-1 ring-border/70">{{ step.number }}</span>{{ step.label }}</div>
          <div v-if="itemKeys.length" class="ml-auto flex items-center gap-2 text-xs text-muted-foreground" aria-label="A/B 审查进度">
            <span>{{ reviewProgress.reviewed }}/{{ reviewProgress.total }} 已审</span>
            <span v-if="currentCaseIndex >= 0" class="text-primary font-medium">第 {{ currentCaseIndex + 1 }} 个</span>
            <span class="text-[11px]">快捷键: 1=A 2=B 3=平 4=败 ←→切换</span>
          </div>
        </div>
      </div>

      <!-- Main content -->
      <div class="flex-1 min-h-0 mx-auto w-full max-w-[1600px] px-4 py-4 sm:px-6 lg:px-8">
        <div v-if="!groups.length" class="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-10 text-center"><div class="font-medium">还没有可比较的对比组</div><p class="mt-1 text-sm text-muted-foreground">创建评测时填写相同的版本对比组，完成两条 Run 后就能在这里进行人工 A/B。</p></div>
        <template v-else>
          <!-- Config row -->
          <div class="grid gap-3 md:grid-cols-4 mb-4">
            <Select v-model="form.group">
  <SelectTrigger class="mt-1.5">
    <SelectValue placeholder="请选择对比组" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem v-for="group in comparisonGroups" :key="group" :value="group">
      {{ group }}
    </SelectItem>
  </SelectContent>
</Select>
            <label class="text-sm font-medium">版本 B<select v-model="form.runB" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm" @change="loadRun('b', form.runB)"><option value="">请选择</option><option v-for="run in groupRuns" :key="run.id" :value="run.id">评测 #{{ run.id }} · {{ run.target_release_key }}</option></select></label>
            <label class="text-sm font-medium">Case<select v-model="form.item" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 text-sm"><option value="">请选择</option><option v-for="key in itemKeys" :key="key" :value="key">{{ reviewedKeys.has(key) ? '✓ ' : '' }}{{ key }}</option></select></label>
          </div>

          <!-- Forced side-by-side comparison -->
          <div class="grid gap-4 lg:grid-cols-2 h-[calc(100vh-340px)] min-h-[400px]">
            <article v-for="entry in [{ item: itemA, label: '回答 A', run: runA }, { item: itemB, label: '回答 B', run: runB }]" :key="entry.label" class="flex flex-col rounded-xl border border-border/70 bg-muted/20 overflow-hidden">
              <div class="shrink-0 flex items-start gap-3 border-b border-border/60 p-4"><div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-background text-primary ring-1 ring-border/70"><ArrowLeftRight class="size-4" /></div><div><h3 class="font-medium">{{ entry.label }}</h3><p class="mt-0.5 text-xs text-muted-foreground">{{ entry.run?.target_release_key || '选择版本后显示' }}</p></div></div>
              <ScrollArea class="flex-1">
                <div class="p-4 space-y-3 text-sm">
                  <div v-if="entry.item" class="grid gap-2 text-xs sm:grid-cols-2">
                    <div v-if="metrics(entry.item).tool_metrics" class="rounded-lg bg-background p-3 ring-1 ring-border/60"><div class="font-medium">工具调用效果</div><div class="mt-1 text-muted-foreground">{{ metrics(entry.item).tool_metrics?.call_count || 0 }} 次调用 · {{ metrics(entry.item).tool_metrics?.failed_call_count || 0 }} 次失败</div></div>
                    <div v-if="metrics(entry.item).intent_metrics" class="rounded-lg bg-background p-3 ring-1 ring-border/60"><div class="font-medium">意图识别效果</div><div class="mt-1 text-muted-foreground">覆盖率 {{ metrics(entry.item).intent_metrics?.intent_coverage == null ? '—' : `${Math.round(metrics(entry.item).intent_metrics.intent_coverage * 100)}%` }}</div></div>
                    <div v-if="metrics(entry.item).metrics?.field_coverage != null" class="rounded-lg bg-background p-3 ring-1 ring-border/60"><div class="font-medium">结构化抽取</div><div class="mt-1 text-muted-foreground">字段覆盖 {{ Math.round(metrics(entry.item).metrics.field_coverage * 100) }}% · 题目召回 {{ Math.round((metrics(entry.item).metrics.question_recall || 0) * 100) }}%</div></div>
                    <div v-if="metrics(entry.item).metrics?.source_fact_coverage != null" class="rounded-lg bg-background p-3 ring-1 ring-border/60"><div class="font-medium">简历事实与岗位</div><div class="mt-1 text-muted-foreground">事实覆盖 {{ Math.round(metrics(entry.item).metrics.source_fact_coverage * 100) }}% · 岗位匹配 {{ Math.round((metrics(entry.item).metrics.target_alignment || 0) * 100) }}%</div></div>
                    <div v-if="metrics(entry.item).metrics?.taxonomy_validity != null" class="rounded-lg bg-background p-3 ring-1 ring-border/60"><div class="font-medium">题目分类</div><div class="mt-1 text-muted-foreground">分类合法 {{ Math.round(metrics(entry.item).metrics.taxonomy_validity * 100) }}% · 标签准确 {{ Math.round((metrics(entry.item).metrics.classification_accuracy || 0) * 100) }}%</div></div>
                  </div>
                  <div v-if="hardAssertions(entry.item).length" class="rounded-lg border border-border/60 p-3">
                    <div class="mb-2 font-medium">硬门禁</div>
                    <div class="space-y-2">
                      <div v-for="a in hardAssertions(entry.item)" :key="a.id" :class="['rounded-md px-2 py-1 text-xs', a.passed ? 'bg-emerald-500/10 text-emerald-700' : 'bg-destructive/10 text-destructive']">
                        <span :class="a.passed ? '' : 'font-medium'">{{ a.passed ? '✓ 通过' : '✗ 失败' }}</span>
                        <span class="ml-1 font-medium">{{ a.id }}</span>
                        <span v-if="a.evidence" class="ml-2 text-muted-foreground">{{ a.evidence }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-if="turns(entry.item).length" class="space-y-3">
                    <div v-for="turn in turns(entry.item)" :key="turn.turn" class="rounded-lg bg-background p-3">
                      <div class="text-xs text-muted-foreground">第 {{ turn.turn }} 轮</div>
                      <div class="mt-2 text-xs text-muted-foreground">候选人：{{ turn.user }}</div>
                      <div class="mt-1 leading-6">面试官：{{ turn.assistant }}</div>
                    </div>
                  </div>
                  <div v-else class="flex min-h-40 items-center justify-center text-center text-sm text-muted-foreground">选择两个版本和 Case 后显示完整回答。</div>
                </div>
              </ScrollArea>
            </article>
          </div>

          <!-- Choice buttons -->
          <div class="mt-4 rounded-xl border border-primary/20 bg-primary/5 p-4">
            <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div><div class="text-sm font-semibold">你的判断</div><p class="mt-1 text-xs text-muted-foreground">只根据当前 Case 的回答质量做选择。快捷键: 1=A 2=B 3=平 4=都失败</p></div>
              <div class="flex flex-wrap gap-2" role="radiogroup" aria-label="人工 A/B 选择">
                <button v-for="choice in [{ key: 'a', label: '1 · A 更好' }, { key: 'b', label: '2 · B 更好' }, { key: 'tie', label: '3 · 平局' }, { key: 'both_fail', label: '4 · 都失败' }]" :key="choice.key" type="button" :aria-pressed="form.choice === choice.key" :class="['rounded-md border px-3 py-2 text-sm transition-colors', form.choice === choice.key ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background hover:border-primary/50']" @click="form.choice = choice.key">{{ choice.label }}</button>
              </div>
            </div>
            <label class="mt-4 block text-sm font-medium">选择依据 <Input v-model="form.comment" class="mt-1.5 bg-background" placeholder="例如：A 的追问更贴近候选人回答" /></label>
            <p v-if="error" class="mt-3 rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p>
            <div class="mt-3 flex justify-end gap-2">
              <Button variant="ghost" size="sm" @click="navigateCase('prev')"><ArrowLeft class="mr-1 size-3" />上一个</Button>
              <Button variant="ghost" size="sm" @click="navigateCase('next')">下一个<ArrowRight class="ml-1 size-3" /></Button>
              <Button :disabled="saving || !form.choice" @click="save"><Check class="mr-1.5 size-4" />{{ saving ? '保存中...' : '保存并下一个' }}</Button>
            </div>
          </div>
        </template>
      </div>
    </template>

    <!-- Saved reviews -->
    <div class="shrink-0 mx-auto w-full max-w-[1600px] px-4 pb-4 sm:px-6 lg:px-8">
      <AppCard title="已保存的人工评测" description="人工选择是独立证据，不会覆盖硬门禁或 LLM Judge 结果。" no-padding>
        <div class="flex justify-end border-b border-border/60 p-3"><Button size="sm" variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button></div>
        <div v-if="!reviews.length" class="p-8 text-center text-sm text-muted-foreground">还没有人工 A/B 记录。</div>
        <div v-else class="divide-y divide-border/60"><div v-for="review in reviews" :key="review.id" class="flex flex-wrap items-center gap-3 p-4 text-sm"><span class="font-medium">{{ review.comparison_group }}</span><span class="rounded-full bg-primary/10 px-2 py-0.5 text-primary">{{ reviewChoiceLabel(review.choice) }}</span><span class="text-muted-foreground">{{ review.item_key }}</span><span class="ml-auto text-xs text-muted-foreground">{{ formatDate(review.created_at) }}</span><span v-if="review.comment" class="basis-full text-muted-foreground">{{ review.comment }}</span></div></div>
      </AppCard>
    </div>
  </div>
</template>
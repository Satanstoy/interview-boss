<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeftRight, Check, RefreshCw } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AppPageHeader from '@/components/common/AppPageHeader.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { createHumanReview, fetchEvaluationRun, fetchEvaluationRuns, fetchHumanReviews } from '@/services/evaluationApi.js'
import { formatDate } from './evaluationShared.js'

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

async function load() {
  loading.value = true
  try {
    const [runData, reviewData] = await Promise.all([fetchEvaluationRuns(), fetchHumanReviews()])
    runs.value = runData.runs || []
    reviews.value = reviewData.reviews || []
    if (!form.value.group) form.value.group = groups.value[0] || ''
  } catch (err) { error.value = err.message || '人工评测加载失败' } finally { loading.value = false }
}
async function loadRun(which, id) {
  if (!id) { if (which === 'a') runA.value = null; else runB.value = null; return }
  try { const data = await fetchEvaluationRun(id); if (which === 'a') runA.value = data; else runB.value = data } catch (err) { error.value = err.message || 'Run 详情加载失败' }
}
async function save() {
  if (!form.value.group || !form.value.item || !form.value.choice || !runA.value || !runB.value) { error.value = '请选择 comparison group、两条 Run、Case 和 A/B 结果'; return }
  saving.value = true; error.value = ''
  try {
    let dimensions = {}
    try { dimensions = JSON.parse(form.value.dimensions || '{}') } catch { throw new Error('维度 JSON 格式不正确') }
    await createHumanReview({ comparison_group: form.value.group, run_a_id: runA.value.id, run_b_id: runB.value.id, item_key: form.value.item, choice: form.value.choice, dimensions, comment: form.value.comment })
    form.value.comment = ''; form.value.choice = ''; await load()
  } catch (err) { error.value = err.message || '保存人工评测失败' } finally { saving.value = false }
}
watch(() => form.value.group, async () => { form.value.runA = ''; form.value.runB = ''; form.value.item = ''; runA.value = null; runB.value = null })
watch(() => form.value.item, () => {})
onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar"><div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    <AppPageHeader title="人工 A/B" description="在相同 Benchmark、Harness、Simulator 和 Judge 上，对两个版本的同一 Case 做盲选或并排选择。" />
    <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
    <template v-else>
      <AppCard class="mt-6" title="创建人工比较" description="人工选择会作为独立指标保存，不覆盖 LLM Judge 结果。">
      <div class="grid gap-4 md:grid-cols-4"><label class="text-sm font-medium">Comparison group<select v-model="form.group" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm"><option value="">请选择</option><option v-for="group in groups" :key="group" :value="group">{{ group }}</option></select></label><label class="text-sm font-medium">Run A<select v-model="form.runA" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm" @change="loadRun('a', form.runA)"><option value="">请选择</option><option v-for="run in groupRuns" :key="run.id" :value="run.id">Run #{{ run.id }}</option></select></label><label class="text-sm font-medium">Run B<select v-model="form.runB" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm" @change="loadRun('b', form.runB)"><option value="">请选择</option><option v-for="run in groupRuns" :key="run.id" :value="run.id">Run #{{ run.id }}</option></select></label><label class="text-sm font-medium">Case × Replication<select v-model="form.item" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm"><option value="">请选择</option><option v-for="key in itemKeys" :key="key" :value="key">{{ key }}</option></select></label></div>
        <div class="mt-5 grid gap-4 lg:grid-cols-2"><div v-for="entry in [{ item: itemA, label: '回答 A' }, { item: itemB, label: '回答 B' }]" :key="entry.label" class="min-h-40 rounded-xl border border-border/70 bg-muted/20 p-4"><div class="mb-3 flex items-center gap-2 font-medium"><ArrowLeftRight class="size-4 text-primary" />{{ entry.label }}</div><div v-if="turns(entry.item).length" class="space-y-3 text-sm"><div v-for="turn in turns(entry.item)" :key="turn.turn" class="rounded-lg bg-background p-3"><div class="text-xs text-muted-foreground">第 {{ turn.turn }} 轮</div><div class="mt-1 text-xs text-muted-foreground">候选人：{{ turn.user }}</div><div class="mt-1">面试官：{{ turn.assistant }}</div></div></div><div v-else class="text-sm text-muted-foreground">选择 Run 和 Case 后显示完整回答。</div></div></div>
        <div class="mt-4 grid gap-3 md:grid-cols-[180px_1fr]"><label class="text-sm font-medium">最终选择<select v-model="form.choice" class="mt-1.5 h-9 w-full rounded-md border border-input bg-background px-3 text-sm"><option value="">请选择</option><option value="a">A 更好</option><option value="b">B 更好</option><option value="tie">平局</option><option value="both_fail">都失败</option></select></label><label class="text-sm font-medium">维度 JSON + 评论<textarea v-model="form.dimensions" class="mt-1.5 min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs" placeholder='{"flow":"a","evidence":"tie"}'></textarea><Input v-model="form.comment" class="mt-2" placeholder="可选：记录选择依据" /></label></div>
        <p v-if="error" class="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">{{ error }}</p><div class="mt-4 flex justify-end"><Button :disabled="saving" @click="save"><Check class="mr-1.5 size-4" />{{ saving ? '保存中...' : '保存人工选择' }}</Button></div>
      </AppCard>
      <AppCard class="mt-6" title="已保存的人工评测" no-padding><div class="flex justify-end border-b border-border/60 p-3"><Button size="sm" variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新</Button></div><div v-if="!reviews.length" class="p-8 text-center text-sm text-muted-foreground">还没有人工 A/B 记录。</div><div v-else class="divide-y divide-border/60"><div v-for="review in reviews" :key="review.id" class="flex flex-wrap items-center gap-3 p-4 text-sm"><span class="font-medium">{{ review.comparison_group }}</span><span class="rounded-full bg-primary/10 px-2 py-0.5 text-primary">{{ review.choice }}</span><span class="text-muted-foreground">{{ review.item_key }}</span><span class="ml-auto text-xs text-muted-foreground">{{ formatDate(review.created_at) }}</span><span v-if="review.comment" class="basis-full text-muted-foreground">{{ review.comment }}</span></div></div></AppCard>
    </template>
  </div></div>
</template>

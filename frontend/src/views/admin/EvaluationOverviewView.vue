<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, ArrowRight, CheckCircle2, Clock3, FlaskConical, XCircle } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AppPageHeader from '@/components/common/AppPageHeader.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { fetchEvaluationOverview, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { formatDate, runProgress, statusClass, statusLabel } from './evaluationShared.js'

const router = useRouter()
const overview = ref(null)
const runs = ref([])
const loading = ref(true)
const error = ref('')

const cards = computed(() => [
  { label: '已完成', value: overview.value?.counts?.completed || 0, icon: CheckCircle2, tone: 'text-emerald-600' },
  { label: '执行中', value: (overview.value?.counts?.running || 0) + (overview.value?.counts?.queued || 0), icon: Activity, tone: 'text-amber-600' },
  { label: '待调度', value: overview.value?.counts?.created || 0, icon: Clock3, tone: 'text-muted-foreground' },
  { label: '失败 / 取消', value: (overview.value?.counts?.failed || 0) + (overview.value?.counts?.cancelled || 0), icon: XCircle, tone: 'text-destructive' },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [summary, runData] = await Promise.all([fetchEvaluationOverview(), fetchEvaluationRuns()])
    overview.value = summary
    runs.value = runData.runs || []
  } catch (err) {
    error.value = err.message || '评测总览加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <AppPageHeader title="测评可视化" description="查看官方 Eval Run 的执行状态、进度和版本绑定关系。">
        <template #actions>
          <Button variant="outline" @click="router.push('/admin/evals/experiments')">
            <FlaskConical class="mr-1.5 size-4" /> 新建测评实验
          </Button>
        </template>
      </AppPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
        {{ error }}
        <Button class="ml-3" size="sm" variant="outline" @click="load">重试</Button>
      </div>
      <template v-else>
        <div class="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <AppCard v-for="card in cards" :key="card.label" class="min-h-28">
            <div class="flex items-start justify-between">
              <div><div class="text-sm text-muted-foreground">{{ card.label }}</div><div class="mt-2 text-3xl font-semibold">{{ card.value }}</div></div>
              <component :is="card.icon" :class="['size-5', card.tone]" />
            </div>
          </AppCard>
        </div>

        <AppCard class="mt-6" title="最近评测" description="每条 Run 都绑定固定的 target、benchmark、harness、simulator 和 judge 版本。">
          <div v-if="!runs.length" class="py-8 text-center text-sm text-muted-foreground">还没有评测 Run，先去“测评实验”创建一批。</div>
          <div v-else class="divide-y divide-border/60">
            <button v-for="run in runs" :key="run.id" type="button" class="flex w-full items-center gap-4 py-4 text-left transition-colors hover:bg-muted/40" @click="router.push(`/admin/evals/runs/${run.id}`)">
              <div class="min-w-0 flex-1"><div class="flex items-center gap-2"><span class="font-medium">Run #{{ run.id }}</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span></div><div class="mt-1 text-xs text-muted-foreground">{{ formatDate(run.created_at) }} · {{ run.target_release_key || '未命名 Target' }}</div></div>
              <div class="hidden w-40 sm:block"><div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>{{ run.completed_items || 0 }} / {{ run.total_items || 0 }}</span><span>{{ runProgress(run) }}%</span></div><div class="h-1.5 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all" :style="{ width: `${runProgress(run)}%` }" /></div></div>
              <ArrowRight class="size-4 shrink-0 text-muted-foreground" />
            </button>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

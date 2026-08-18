<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, RefreshCw } from '@lucide/vue'
import { useRouter } from 'vue-router'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { fetchEvaluationOverview, fetchEvaluationRuns } from '@/services/evaluationApi.js'
import { formatDate, qualityStatusLabel, runProgress, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const router = useRouter()
const overview = ref(null)
const runs = ref([])
const loading = ref(true)
const error = ref('')

const cards = computed(() => [
  { label: '已完成', value: overview.value?.counts?.completed || 0 },
  { label: '正在执行', value: (overview.value?.counts?.running || 0) + (overview.value?.counts?.queued || 0) },
  { label: '等待启动', value: overview.value?.counts?.created || 0 },
  { label: '失败或取消', value: (overview.value?.counts?.failed || 0) + (overview.value?.counts?.cancelled || 0) },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [summary, runData] = await Promise.all([fetchEvaluationOverview(), fetchEvaluationRuns()])
    overview.value = summary
    runs.value = runData.runs || []
  } catch (err) {
    error.value = err.message || '评测结果加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader
        title="评测结果"
        description="查看每次完整 E2E 的实时进度、逐 Case 结果和最终聚合状态。"
        active-key="results"
      >
        <template #actions>
          <Button variant="ghost" @click="load"><RefreshCw class="mr-1.5 size-4" />刷新结果</Button>
        </template>
      </EvaluationPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
        {{ error }}
        <Button class="ml-3" size="sm" variant="outline" @click="load">重试</Button>
      </div>
      <template v-else>
        <div class="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <AppCard v-for="card in cards" :key="card.label" class="min-h-24">
            <div class="text-sm text-muted-foreground">{{ card.label }}</div>
            <div class="mt-2 text-3xl font-semibold">{{ card.value }}</div>
          </AppCard>
        </div>

        <AppCard class="mt-6" title="最近评测运行" description="点击一条记录查看完整 E2E 进度、逐 Case 结果和版本绑定。">
          <div v-if="!runs.length" class="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-10 text-center">
            <div class="font-medium">还没有评测记录</div>
            <p class="mt-1 text-sm text-muted-foreground">先在“测评实验”中选择一个被测版本，创建一场完整 E2E 评测。</p>
            <Button class="mt-4" size="sm" @click="router.push('/admin/evals/experiments')">开始一次完整评测</Button>
          </div>
          <div v-else class="divide-y divide-border/60">
            <button
              v-for="run in runs"
              :key="run.id"
              type="button"
              class="flex w-full items-center gap-4 py-4 text-left transition-colors hover:bg-muted/40"
              @click="router.push(`/admin/evals/runs/${run.id}`)"
            >
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="font-medium">评测 #{{ run.id }}</span>
                  <span class="text-[11px] text-muted-foreground">执行</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><span class="text-[11px] text-muted-foreground">质量</span><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.quality_status)]">{{ qualityStatusLabel(run.quality_status) }}</span>
                </div>
                <div class="mt-1 text-xs text-muted-foreground">{{ formatDate(run.created_at) }} · 被测版本：{{ run.target_release_key || '未命名' }}</div>
              </div>
              <div class="hidden w-40 sm:block">
                <div class="mb-1 flex justify-between text-xs text-muted-foreground"><span>已处理 {{ run.completed_items || 0 }} / {{ run.total_items || 0 }} Cases</span><span>{{ runProgress(run) }}%</span></div>
                <div class="h-1.5 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all" :style="{ width: `${runProgress(run)}%` }" /></div>
              </div>
              <ArrowRight class="size-4 shrink-0 text-muted-foreground" />
            </button>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, CheckCircle2, Clock3, FlaskConical, XCircle } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Button } from '@/components/ui/button'
import { fetchEvaluationOverview } from '@/services/evaluationApi.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const router = useRouter()
const overview = ref(null)
const loading = ref(true)
const error = ref('')
const humanReviews = computed(() => overview.value?.human_reviews || { total: 0, comparison_groups: [] })

const cards = computed(() => [
  { label: '已完成', value: overview.value?.counts?.completed || 0, icon: CheckCircle2, tone: 'text-emerald-600' },
  { label: '正在执行', hint: '队列中或 E2E 运行中', value: (overview.value?.counts?.running || 0) + (overview.value?.counts?.queued || 0), icon: Activity, tone: 'text-amber-600' },
  { label: '等待启动', hint: '已经创建，等待 Worker', value: overview.value?.counts?.created || 0, icon: Clock3, tone: 'text-muted-foreground' },
  { label: '失败或取消', hint: '需要进一步查看原因', value: (overview.value?.counts?.failed || 0) + (overview.value?.counts?.cancelled || 0), icon: XCircle, tone: 'text-destructive' },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await fetchEvaluationOverview()
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
      <EvaluationPageHeader
        title="测评可视化"
        description="站在五步评测流程之上，快速查看系统状态、人工证据和下一步需要处理的事项。"
        :show-flow="false"
      >
        <template #actions>
          <Button variant="outline" @click="router.push('/admin/evals/experiments')">
            <FlaskConical class="mr-1.5 size-4" /> 开始一次完整评测
          </Button>
        </template>
      </EvaluationPageHeader>

      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <div v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
        {{ error }}
        <Button class="ml-3" size="sm" variant="outline" @click="load">重试</Button>
      </div>
      <template v-else>
        <div class="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <AppCard v-for="card in cards" :key="card.label" class="min-h-28">
            <div class="flex items-start justify-between">
              <div><div class="text-sm text-muted-foreground">{{ card.label }}</div><div class="mt-2 text-3xl font-semibold">{{ card.value }}</div><div class="mt-1 text-xs text-muted-foreground">{{ card.hint || '累计运行数量' }}</div></div>
              <component :is="card.icon" :class="['size-5', card.tone]" />
            </div>
          </AppCard>
        </div>

        <AppCard class="mt-6" title="人工 A/B 汇总" description="人工判断是独立质量证据，用来核验版本差异，不覆盖 Hard Gate 或 Judge。">
          <div class="mb-4 flex items-center justify-between rounded-lg bg-muted/30 px-4 py-3">
            <span class="text-sm text-muted-foreground">已完成人工比较</span>
            <span class="text-2xl font-semibold">{{ humanReviews.total }}</span>
          </div>
          <div v-if="!humanReviews.comparison_groups.length" class="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-8 text-center text-sm text-muted-foreground">
            还没有人工 A/B 数据。完成两条同一 comparison group 的 E2E Run 后，可以进入人工 A/B 核验。
          </div>
          <div v-else class="divide-y divide-border/60">
            <div v-for="group in humanReviews.comparison_groups" :key="`${group.comparison_group}-${group.run_a_id}-${group.run_b_id}`" class="flex flex-wrap items-center gap-3 py-4">
              <div class="min-w-48 flex-1">
                <div class="font-medium">{{ group.comparison_group }}</div>
                <div class="mt-1 text-xs text-muted-foreground">{{ group.run_a_target_release_key }} 对比 {{ group.run_b_target_release_key }}</div>
              </div>
              <div class="flex flex-wrap gap-2 text-xs">
                <span class="rounded-full bg-emerald-500/10 px-2 py-1 text-emerald-700">A 胜 {{ group.a_wins }}</span>
                <span class="rounded-full bg-blue-500/10 px-2 py-1 text-blue-700">B 胜 {{ group.b_wins }}</span>
                <span class="rounded-full bg-muted px-2 py-1 text-muted-foreground">平局 {{ group.ties }}</span>
                <span class="rounded-full bg-destructive/10 px-2 py-1 text-destructive">都失败 {{ group.both_fail }}</span>
              </div>
              <Button size="sm" variant="ghost" @click="router.push({ path: '/admin/evals/reviews', query: { group: group.comparison_group } })">进入人工 A/B</Button>
            </div>
          </div>
        </AppCard>
      </template>
    </div>
  </div>
</template>

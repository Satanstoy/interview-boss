<script setup>
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, GitBranch } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { fetchEvaluationBenchmarks, fetchEvaluationReleases } from '@/services/evaluationApi.js'
import { formatDate, releaseTypeMeta, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'
import { Badge } from '@/components/ui/badge'

const releases = ref([])
const loading = ref(true)
const error = ref('')
const opened = ref(null)
const benchmarks = ref([])

const groups = computed(() => (
  ['target', 'evaluation']
    .map(type => ({ type, ...releaseTypeMeta(type), items: releases.value.filter(release => release.release_type === type) }))
    .filter(group => group.items.length)
))

function manifestOf(release) {
  if (release?.manifest && typeof release.manifest === 'object') return release.manifest
  try { return JSON.parse(release?.manifest_json || '{}') } catch { return {} }
}

function fixedItems(release) {
  const manifest = manifestOf(release)
  if (release.release_type === 'evaluation') {
    const items = [
      `题集 ${manifest.benchmark?.suite_key || '已固化'}`,
      `Judge ${manifest.judge?.model || release.judge_model || '已固化'}`,
      `执行器 ${manifest.simulator_harness?.version || '1.0'}`,
    ]
    if (manifest.candidate_simulator) items.push(`候选人 ${manifest.candidate_simulator.model || '已固化'}`)
    if (manifest.tool_evaluation?.enabled) items.push('工具调用效果')
    if (manifest.intent_evaluation?.enabled) items.push('意图识别效果')
    if (manifest.protocol?.deterministic_weight != null || manifest.protocol?.judge_weight != null) {
      const deterministic = Math.round(Number(manifest.protocol.deterministic_weight || 0) * 100)
      const judge = Math.round(Number(manifest.protocol.judge_weight || 0) * 100)
      items.push(`混合评分：规则 ${deterministic}% + Judge ${judge}%`)
    }
    if (manifest.structured_evaluation) items.push('结构化字段与事实依据')
    if (manifest.resume_evaluation) items.push('简历事实与岗位匹配')
    if (manifest.tagging_evaluation) items.push('分类、标签与难度')
    return items
  }
  return [
    manifest.workflow ? `Workflow ${manifest.workflow}` : '',
    manifest.model ? `模型 ${manifest.model}` : '',
    release.git_sha ? `Git ${release.git_sha.slice(0, 12)}` : '',
  ].filter(Boolean)
}

function benchmarkOf(release) {
  if (release.release_type !== 'evaluation') return null
  const key = release.release_key
  return benchmarks.value.find(s => (s.evaluation_release_key || s.release_key) === key) || null
}

function toggle(id) {
  opened.value = opened.value === id ? null : id
}

async function load() {
  try {
    releases.value = (await fetchEvaluationReleases()).releases || []
  } catch (err) {
    error.value = err.message || '版本列表加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div aria-labelledby="eval-evaluationreleases-title" class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader title="版本与发布：决定测谁" description="先选择被测对象版本，再绑定一个完整评测版本。完整评测版本会固定适合该目标的题集、规则、模型、执行器和确定性指标；模拟面试额外固定模拟器、工具调用与意图识别。" active-key="releases" />
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <p v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
      <div aria-live="polite" v-else class="mt-6 space-y-5">
        <AppCard v-for="group in groups" :key="group.type" :title="group.title" :description="group.description" no-padding>
          <div class="overflow-x-auto">
            <table class="w-full table-fixed text-left text-sm">
              <thead class="border-b border-border/60 bg-muted/30 text-xs text-muted-foreground"><tr><th class="w-[25%] px-3 py-3 font-medium sm:px-5">版本</th><th class="w-[12%] px-3 py-3 font-medium sm:px-5">状态</th><th class="w-[43%] px-3 py-3 font-medium sm:px-5">这一个版本固定了什么</th><th class="w-[15%] px-3 py-3 font-medium sm:px-5">创建时间</th><th class="w-[5%] px-3 py-3 font-medium sm:px-5"></th></tr></thead>
              <tbody class="divide-y divide-border/60">
                <template v-for="release in group.items" :key="release.id">
                  <tr class="hover:bg-muted/20">
                    <td class="align-top overflow-hidden px-3 py-4 sm:px-5"><div class="flex min-w-0 items-start gap-1.5 font-medium sm:gap-2"><GitBranch class="mt-0.5 size-4 shrink-0 text-primary" /><span class="break-all">{{ release.release_key }}</span></div><div class="mt-1 break-words text-xs text-muted-foreground">版本 {{ release.version }} · {{ release.target_type || '通用' }}</div></td>
                    <td class="align-top px-3 py-4 sm:px-5"><Badge variant="default">{{ statusLabel(release.status) }}</Badge></td>
                    <td class="align-top break-words px-3 py-4 text-xs text-muted-foreground sm:px-5"><div class="flex flex-wrap gap-1.5"><span v-for="item in fixedItems(release)" :key="item" class="rounded-md bg-muted px-2 py-1 text-foreground">{{ item }}</span><span v-if="!fixedItems(release).length">内容记录在版本快照中</span></div></td>
                    <td class="align-top break-all px-3 py-4 text-xs text-muted-foreground sm:px-5">{{ formatDate(release.created_at) }}</td>
                    <td class="align-top px-3 py-4 text-right sm:px-5"><button type="button" class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" :aria-label="`查看 ${release.release_key} 详情`" @click="toggle(release.id)"><ChevronDown :class="['size-4 transition-transform', opened === release.id ? 'rotate-180' : '']" /></button></td>
                  </tr>
                  <tr v-if="opened === release.id" class="bg-muted/20"><td colspan="5" class="px-5 py-4"><div class="grid gap-3 text-xs sm:grid-cols-3"><div><div class="text-muted-foreground">Manifest Digest</div><div class="mt-1 break-all font-mono text-foreground">{{ release.manifest_digest || '—' }}</div></div><div><div class="text-muted-foreground">Git SHA</div><div class="mt-1 break-all font-mono text-foreground">{{ release.git_sha || '—' }}</div></div><div><div class="text-muted-foreground">配置摘要</div><div class="mt-1 break-all font-mono text-foreground">{{ release.config_digest || '—' }}</div></div></div>
                    <div v-if="benchmarkOf(release)" class="mt-4 rounded-lg border border-border/60 p-3">
                      <div class="mb-2 font-medium">Benchmark 题集 · {{ benchmarkOf(release).cases?.length || 0 }} 个 Case</div>
                      <div v-if="!benchmarkOf(release).cases?.length" class="text-xs text-muted-foreground">该题集暂无已固化的 Case。</div>
                      <div v-else class="space-y-2">
                        <div v-for="benchCase in benchmarkOf(release).cases" :key="benchCase.id" class="rounded-md bg-muted/40 p-2">
                          <div class="flex items-center gap-2"><span class="font-medium">{{ benchCase.case_key }}</span><span class="text-xs text-muted-foreground">场景 {{ benchCase.scenario_key || '—' }}</span></div>
                          <div v-if="Object.keys(benchCase.contract || {}).length" class="mt-1 text-xs text-muted-foreground">硬约束 {{ (benchCase.contract?.hard_assertions || []).length }} 项 · 量规 {{ Object.keys(benchCase.contract?.rubric || {}).join('、') || '—' }}</div>
                        </div>
                      </div>
                    </div></td></tr>
                </template>
              </tbody>
            </table>
          </div>
        </AppCard>
        <div v-if="!groups.length" class="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">暂无可用的被测版本或完整评测版本。</div>
      </div>
    </div>
  </div>
</template>
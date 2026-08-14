<script setup>
import { onMounted, ref } from 'vue'
import { GitBranch } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AppPageHeader from '@/components/common/AppPageHeader.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { fetchEvaluationReleases } from '@/services/evaluationApi.js'
import { formatDate, releaseTypeLabel, statusClass, statusLabel } from './evaluationShared.js'

const releases = ref([])
const loading = ref(true)
const error = ref('')
async function load() {
  try { releases.value = (await fetchEvaluationReleases()).releases || [] } catch (err) { error.value = err.message || '版本列表加载失败' } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar"><div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    <AppPageHeader title="版本与发布" description="每个 Agent、Workflow、Harness、Candidate Simulator、Judge 和协议都独立版本化；Run 只绑定已发布版本。" />
    <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
    <p v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
    <AppCard v-else class="mt-6" no-padding>
      <div class="overflow-x-auto"><table class="w-full min-w-[850px] text-left text-sm"><thead class="border-b border-border/60 bg-muted/30 text-xs text-muted-foreground"><tr><th class="px-5 py-3 font-medium">Release</th><th class="px-5 py-3 font-medium">类型</th><th class="px-5 py-3 font-medium">状态</th><th class="px-5 py-3 font-medium">Judge Model</th><th class="px-5 py-3 font-medium">Manifest Digest</th><th class="px-5 py-3 font-medium">代码 / 镜像</th><th class="px-5 py-3 font-medium">创建时间</th></tr></thead><tbody class="divide-y divide-border/60"><tr v-for="release in releases" :key="release.id" class="hover:bg-muted/20"><td class="px-5 py-4"><div class="flex items-center gap-2 font-medium"><GitBranch class="size-4 text-primary" />{{ release.release_key }}</div><div class="mt-1 text-xs text-muted-foreground">v{{ release.version }}</div></td><td class="px-5 py-4 text-muted-foreground">{{ releaseTypeLabel(release.release_type) }}</td><td class="px-5 py-4"><span :class="['rounded-full px-2 py-0.5 text-xs', statusClass(release.status)]">{{ statusLabel(release.status) }}</span></td><td class="px-5 py-4 font-mono text-xs">{{ release.judge_model || '—' }}</td><td class="px-5 py-4 font-mono text-xs text-muted-foreground">{{ release.manifest_digest?.slice(0, 16) }}…</td><td class="px-5 py-4 text-xs text-muted-foreground"><div>{{ release.git_sha || '—' }}</div><div>{{ release.image_digest || '—' }}</div></td><td class="px-5 py-4 text-xs text-muted-foreground">{{ formatDate(release.created_at) }}</td></tr></tbody></table></div>
      <div v-if="!releases.length" class="p-8 text-center text-sm text-muted-foreground">暂无 Release。</div>
    </AppCard>
  </div></div>
</template>

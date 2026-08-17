<script setup>
import { computed, onMounted, ref } from 'vue'
import { ChevronDown, GitBranch } from '@lucide/vue'
import AppCard from '@/components/common/AppCard.vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { fetchEvaluationReleases } from '@/services/evaluationApi.js'
import { formatDate, releaseTypeMeta, releaseTypeLabel, statusClass, statusLabel } from './evaluationShared.js'
import EvaluationPageHeader from './EvaluationPageHeader.vue'

const releases = ref([])
const loading = ref(true)
const error = ref('')
const opened = ref(null)

const groups = computed(() => {
  const order = ['target', 'benchmark_suite', 'eval_protocol', 'judge', 'simulator_harness', 'candidate_simulator']
  return order.map(type => ({ type, ...releaseTypeMeta(type), items: releases.value.filter(release => release.release_type === type) })).filter(group => group.items.length)
})

async function load() {
  try {
    releases.value = (await fetchEvaluationReleases()).releases || []
  } catch (err) {
    error.value = err.message || '版本列表加载失败'
  } finally {
    loading.value = false
  }
}

function toggle(id) {
  opened.value = opened.value === id ? null : id
}

onMounted(load)
</script>

<template>
  <div class="h-full overflow-y-auto custom-scrollbar">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <EvaluationPageHeader title="版本与发布：决定测谁" description="这里管理评测所需的不可变版本。只有已发布版本可以进入正式 Benchmark，历史版本不会被覆盖。" active-key="releases" />
      <div v-if="loading" class="flex min-h-64 items-center justify-center"><AsyncLoading /></div>
      <p v-else-if="error" class="mt-6 rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive">{{ error }}</p>
      <div v-else class="mt-6 space-y-5">
        <AppCard v-for="group in groups" :key="group.type" :title="group.title" :description="group.description" no-padding>
          <div class="overflow-x-auto">
            <table class="w-full table-fixed text-left text-sm">
              <thead class="border-b border-border/60 bg-muted/30 text-xs text-muted-foreground"><tr><th class="w-[25%] px-3 py-3 font-medium sm:px-5">版本</th><th class="w-[12%] px-3 py-3 font-medium sm:px-5">状态</th><th class="w-[31%] px-3 py-3 font-medium sm:px-5">关键固定项</th><th class="w-[20%] px-3 py-3 font-medium sm:px-5">创建时间</th><th class="w-[12%] px-3 py-3 font-medium sm:px-5"></th></tr></thead>
              <tbody class="divide-y divide-border/60">
                <template v-for="release in group.items" :key="release.id">
                  <tr class="hover:bg-muted/20">
                    <td class="align-top overflow-hidden px-3 py-4 sm:px-5"><div class="flex min-w-0 items-start gap-1.5 font-medium sm:gap-2"><GitBranch class="mt-0.5 size-4 shrink-0 text-primary" /><span class="break-all">{{ release.release_key }}</span></div><div class="mt-1 break-words text-xs text-muted-foreground">版本 {{ release.version }} · {{ releaseTypeLabel(release.release_type) }}</div></td>
                    <td class="align-top px-3 py-4 sm:px-5"><span :class="['inline-block rounded-full px-2 py-0.5 text-xs', statusClass(release.status)]">{{ statusLabel(release.status) }}</span></td>
                    <td class="align-top break-words px-3 py-4 text-xs text-muted-foreground sm:px-5"><span v-if="release.judge_model" class="break-all font-mono text-foreground">{{ release.judge_model }}</span><span v-else-if="release.git_sha" class="break-all font-mono text-foreground">Git {{ release.git_sha.slice(0, 12) }}</span><span v-else-if="release.image_digest" class="break-all font-mono text-foreground">Image {{ release.image_digest.slice(0, 12) }}</span><span v-else>已记录在 Manifest</span></td>
                    <td class="align-top break-all px-3 py-4 text-xs text-muted-foreground sm:px-5">{{ formatDate(release.created_at) }}</td>
                    <td class="align-top px-3 py-4 text-right sm:px-5"><button type="button" class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" :aria-label="`查看 ${release.release_key} 详情`" @click="toggle(release.id)"><ChevronDown :class="['size-4 transition-transform', opened === release.id ? 'rotate-180' : '']" /></button></td>
                  </tr>
                  <tr v-if="opened === release.id" class="bg-muted/20"><td colspan="5" class="px-5 py-4"><div class="grid gap-3 text-xs sm:grid-cols-3"><div><div class="text-muted-foreground">Manifest Digest</div><div class="mt-1 break-all font-mono text-foreground">{{ release.manifest_digest || '—' }}</div></div><div><div class="text-muted-foreground">Git SHA</div><div class="mt-1 break-all font-mono text-foreground">{{ release.git_sha || '—' }}</div></div><div><div class="text-muted-foreground">Image Digest</div><div class="mt-1 break-all font-mono text-foreground">{{ release.image_digest || '—' }}</div></div></div></td></tr>
                </template>
              </tbody>
            </table>
          </div>
        </AppCard>
        <div v-if="!groups.length" class="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">暂无 Release。</div>
      </div>
    </div>
  </div>
</template>

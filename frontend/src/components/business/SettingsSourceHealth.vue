<script setup>
import { ref, onMounted } from 'vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { GitMerge, Loader2, Link2, AlertTriangle } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  fetchDuplicateGroups,
  mergeDuplicateGroup,
} from '@/services/adminSourceHealthApi.js'

const { success: toastSuccess, error: toastError } = useToast()
const { confirm: showConfirm } = useConfirm()

const table = ref('interview')
const groups = ref([])
const loading = ref(false)
const processing = ref(new Set())

const tableTabs = [
  { id: 'interview', label: '面经' },
  { id: 'jd', label: 'JD' },
]

const loadGroups = async () => {
  loading.value = true
  try {
    groups.value = await fetchDuplicateGroups(table.value)
  } catch (e) {
    toastError('加载重复面经失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

const switchTable = async (t) => {
  if (table.value === t) return
  table.value = t
  await loadGroups()
}

const onMerge = async (group) => {
  const keepUrl = group.records?.[0]?.url || ''
  const ok = await showConfirm(
    '确认合并该重复组？',
    `将签名「${group.signature}」的 ${group.count} 条公共${table.value === 'jd' ? 'JD' : '面经'}合并为 1 条（保留 id=${group.keep_id}${keepUrl ? '，' + keepUrl.slice(0, 60) : ''}），其余软删可恢复。`,
  )
  if (!ok) return
  processing.value.add(group.signature)
  try {
    const result = await mergeDuplicateGroup(group.signature, table.value, false)
    toastSuccess(`已合并 ${result.merged_count} 条重复记录`)
    await loadGroups()
  } catch (e) {
    toastError('合并失败：' + (e?.message || e))
  } finally {
    processing.value.delete(group.signature)
  }
}

onMounted(loadGroups)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-1.5 rounded-lg border border-border p-1 w-fit">
      <button
        v-for="t in tableTabs"
        :key="t.id"
        class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
        :class="table === t.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
        @click="switchTable(t.id)"
      >
        {{ t.label }}
      </button>
    </div>

    <div v-if="loading" class="flex justify-center py-10 text-muted-foreground">
      <Loader2 :size="20" class="animate-spin" />
    </div>

    <div v-else-if="!groups.length" class="py-10 text-center text-sm text-muted-foreground">
      <GitMerge :size="28" class="mx-auto mb-2 opacity-40" />
      暂无重复的公共{{ table === 'jd' ? 'JD' : '面经' }}
    </div>

    <div v-else class="space-y-2.5">
      <div
        v-for="group in groups"
        :key="group.signature"
        class="rounded-lg border border-border bg-card p-3.5"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5 mb-1.5">
              <Badge variant="secondary" class="text-[11px]">
                {{ group.signature }}
              </Badge>
              <Badge class="bg-amber-500/15 text-amber-600 text-[11px]">
                {{ group.count }} 条重复
              </Badge>
              <span class="text-[11px] text-muted-foreground">
                保留 id={{ group.keep_id }}
              </span>
            </div>
            <div class="space-y-1">
              <div
                v-for="r in group.records"
                :key="r.id"
                class="flex items-center gap-1.5 text-xs"
                :class="r.id === group.keep_id ? 'text-foreground' : 'text-muted-foreground'"
              >
                <Link2 :size="12" class="shrink-0" />
                <span class="shrink-0 text-muted-foreground">#{{ r.id }}</span>
                <span class="truncate font-mono">{{ r.url || '（无链接）' }}</span>
              </div>
            </div>
          </div>

          <div class="flex shrink-0 flex-col gap-1">
            <Button
              variant="destructive"
              size="sm"
              class="h-7 gap-1 text-xs"
              :disabled="processing.has(group.signature)"
              @click="onMerge(group)"
            >
              <AlertTriangle :size="13" />
              合并
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

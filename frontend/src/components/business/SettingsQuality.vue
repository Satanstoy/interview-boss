<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { ClipboardCheck, ShieldCheck, ShieldX, Check, X, Sparkles, Loader2, ArrowRight } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import {
  fetchQualityIssues,
  approveQualityIssue,
  rejectQualityIssue,
  batchApproveQualityIssues,
} from '@/services/adminQualityApi.js'

const { success: toastSuccess, error: toastError } = useToast()
const { confirm: showConfirm } = useConfirm()

const status = ref('pending')
const issues = ref([])
const loading = ref(false)
const processing = ref(new Set())
const busy = ref(false)

const statusTabs = [
  { id: 'pending', label: '待审批' },
  { id: 'done', label: '已处理' },
  { id: 'rejected', label: '已拒绝' },
]

const pendingIssues = computed(() => issues.value.filter((i) => i.status === 'pending'))
const highConfidencePending = computed(() => pendingIssues.value.filter((i) => i.confidence >= 0.85))
const selectedIds = ref(new Set())
const lastSelectedIndex = ref(null)
const selectedPendingIssues = computed(() =>
  pendingIssues.value.filter((issue) => selectedIds.value.has(issue.id)),
)
const selectedLowConfidenceIssues = computed(() =>
  selectedPendingIssues.value.filter((issue) => issue.confidence < 0.85),
)
const allPendingSelected = computed(() =>
  pendingIssues.value.length > 0 && pendingIssues.value.every((issue) => selectedIds.value.has(issue.id)),
)
const selectionState = computed(() => {
  if (allPendingSelected.value) return true
  if (selectedPendingIssues.value.length) return 'indeterminate'
  return false
})

const issueTypeColor = (type) => {
  if (type === 'mismerge') return 'bg-red-500/15 text-red-600'
  if (type === 'duplicate') return 'bg-amber-500/15 text-amber-600'
  return 'bg-blue-500/15 text-blue-600'
}

// 目标题语义：操作后「原题」变成什么。
// split → 被拆出的问法成为新独立题（用 LLM 重写题面 suggested_value，无则原问法）；
// refine → LLM 建议的规范题面；merge → 并入的目标题；dedupe → 移除后原题保持。
const targetOf = (issue) => {
  const action = issue.suggested_action
  if (action === 'merge') {
    return { label: '并入到 #' + issue.target_qb_id, text: issue.target_question }
  }
  if (action === 'refine_representative') {
    return { label: '新代表题', text: issue.suggested_value }
  }
  if (action === 'split') {
    return { label: '新独立题', text: issue.suggested_value || issue.variant }
  }
  return { label: '目标题', text: issue.question }
}

// 分类变化：操作后新题分类与当前不同才返回展示文本（相同则空 → 不显示）
const catChange = (issue) => {
  const action = issue.suggested_action
  let newCat
  if (action === 'split') newCat = issue.new_cat2
  else if (action === 'merge') newCat = issue.target_cat2
  if (!newCat) return ''
  if (newCat === issue.cat2) return ''
  return `分类：${issue.cat2 || '（无）'} → ${newCat}`
}

const loadIssues = async () => {
  loading.value = true
  try {
    issues.value = await fetchQualityIssues(status.value)
  } catch (e) {
    toastError('加载清单失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

const resetSelection = () => {
  selectedIds.value = new Set()
  lastSelectedIndex.value = null
}

const removeFromSelection = (issueId) => {
  const next = new Set(selectedIds.value)
  next.delete(issueId)
  selectedIds.value = next
  // 当前题目从清单消失后，旧索引不再可靠，下一次 Shift 点击从新锚点开始。
  lastSelectedIndex.value = null
}

const toggleSelectAll = () => {
  selectedIds.value = allPendingSelected.value
    ? new Set()
    : new Set(pendingIssues.value.map((issue) => issue.id))
  lastSelectedIndex.value = null
}

// 支持 Shift 点击：从上一次点击的题目选到本次点击的题目。
const toggleIssueSelection = (issue, index, event) => {
  if (status.value !== 'pending' || busy.value || processing.value.has(issue.id)) return

  const checked = !selectedIds.value.has(issue.id)
  const next = new Set(selectedIds.value)
  const hasRangeAnchor = event?.shiftKey && lastSelectedIndex.value !== null

  if (hasRangeAnchor) {
    const start = Math.min(lastSelectedIndex.value, index)
    const end = Math.max(lastSelectedIndex.value, index)
    issues.value.slice(start, end + 1).forEach((rangeIssue) => {
      if (rangeIssue.status !== 'pending') return
      if (checked) next.add(rangeIssue.id)
      else next.delete(rangeIssue.id)
    })
  } else if (checked) {
    next.add(issue.id)
  } else {
    next.delete(issue.id)
  }

  selectedIds.value = next
  lastSelectedIndex.value = index
}

const qualityRoot = ref(null)

const getScrollContainer = () => qualityRoot.value?.closest('.overflow-y-auto.custom-scrollbar')

// 审批后列表会移除当前卡片，保留设置页内部滚动容器的位置，避免用户被带回页面顶部。
const withScrollPreserved = async (action) => {
  const scrollContainer = getScrollContainer()
  const scrollTop = scrollContainer ? scrollContainer.scrollTop : window.scrollY
  const scrollLeft = scrollContainer ? scrollContainer.scrollLeft : window.scrollX
  try {
    return await action()
  } finally {
    await nextTick()
    if (scrollContainer) {
      scrollContainer.scrollTo({ top: scrollTop, left: scrollLeft, behavior: 'auto' })
    } else {
      window.scrollTo({ top: scrollTop, left: scrollLeft, behavior: 'auto' })
    }
  }
}

const setProcessing = (issueId, value) => {
  const next = new Set(processing.value)
  if (value) next.add(issueId)
  else next.delete(issueId)
  processing.value = next
}

const switchStatus = async (s) => {
  resetSelection()
  status.value = s
  await loadIssues()
}

const onApprove = async (issue) => {
  const t = targetOf(issue)
  // 纯确认门：前后对照已在卡片上看过，弹窗只做最后确认
  const ok = await showConfirm(
    `确认${issue.action_label}？`,
    t.text
      ? `操作后：${t.label}「${t.text?.slice(0, 40)}」`
      : `将执行「${issue.action_label}」`,
  )
  if (!ok) return
  setProcessing(issue.id, true)
  try {
    await withScrollPreserved(async () => {
      await approveQualityIssue(issue.id)
      toastSuccess('已执行：' + issue.action_label)
      removeFromSelection(issue.id)
      await loadIssues()
    })
  } catch (e) {
    toastError('执行失败：' + (e?.message || e))
  } finally {
    setProcessing(issue.id, false)
  }
}

const onReject = async (issue) => {
  const ok = await showConfirm('拒绝该建议？', '记录将保留为已拒绝（负样本），不会修改数据。')
  if (!ok) return
  setProcessing(issue.id, true)
  try {
    await withScrollPreserved(async () => {
      await rejectQualityIssue(issue.id)
      toastSuccess('已拒绝')
      removeFromSelection(issue.id)
      await loadIssues()
    })
  } catch (e) {
    toastError('拒绝失败：' + (e?.message || e))
  } finally {
    setProcessing(issue.id, false)
  }
}

const runBatchApprove = async (ids, title, description) => {
  if (!ids.length) return
  const ok = await showConfirm(title, description)
  if (!ok) return
  busy.value = true
  try {
    await withScrollPreserved(async () => {
      const result = await batchApproveQualityIssues(ids)
      toastSuccess(`已批准 ${result.approved?.length || 0} 条`)
      if (result.failed?.length) {
        toastError(`${result.failed.length} 条未批准（置信度不足或已被处理）`)
      }
      resetSelection()
      await loadIssues()
    })
  } catch (e) {
    toastError('批量批准失败：' + (e?.message || e))
  } finally {
    busy.value = false
  }
}

const onBatchApprove = async () => {
  const ids = highConfidencePending.value.map((i) => i.id)
  await runBatchApprove(
    ids,
    `批量批准 ${ids.length} 条高置信建议（≥0.85）？`,
    '仅处理置信度足够高的建议，其余保持待审批。',
  )
}

const onBatchApproveSelected = async () => {
  const ids = selectedPendingIssues.value.map((issue) => issue.id)
  const lowConfidenceCount = selectedLowConfidenceIssues.value.length
  const description = lowConfidenceCount
    ? `其中 ${lowConfidenceCount} 条置信度低于 0.85，将由系统保留为待审批；其余符合条件的建议会被批准。`
    : '将批准当前选中的建议。'
  await runBatchApprove(ids, `批量批准选中的 ${ids.length} 条建议？`, description)
}

onMounted(loadIssues)
</script>

<template>
  <div ref="qualityRoot" class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1.5 rounded-lg border border-border p-1">
        <button
          v-for="tab in statusTabs"
          :key="tab.id"
          class="rounded-md px-3 py-1 text-xs font-medium transition-colors"
          :class="status === tab.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
          @click="switchStatus(tab.id)"
        >
          {{ tab.label }}
        </button>
      </div>
      <Button
        v-if="status === 'pending' && highConfidencePending.length"
        variant="outline"
        size="sm"
        :disabled="busy"
        @click="onBatchApprove"
      >
        <Sparkles :size="14" class="mr-1" />
        批量批准高置信（{{ highConfidencePending.length }}）
      </Button>
    </div>

    <div
      v-if="status === 'pending' && pendingIssues.length"
      class="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card p-3"
    >
      <Checkbox
        :model-value="selectionState"
        aria-label="选择当前清单中的全部待审批题目"
        :disabled="busy"
        @click.stop.prevent="toggleSelectAll"
      />
      <span class="text-xs text-muted-foreground">
        已选 {{ selectedPendingIssues.length }} / {{ pendingIssues.length }} 条
      </span>
      <Button variant="ghost" size="sm" class="h-7 text-xs" :disabled="busy" @click="toggleSelectAll">
        {{ allPendingSelected ? '取消全选' : '全选当前清单' }}
      </Button>
      <Button
        v-if="selectedPendingIssues.length"
        variant="default"
        size="sm"
        class="h-7 gap-1 text-xs"
        :disabled="busy"
        @click="onBatchApproveSelected"
      >
        <Check :size="13" />
        批量批准选中（{{ selectedPendingIssues.length }}）
      </Button>
      <span v-if="selectedLowConfidenceIssues.length" class="text-[11px] text-muted-foreground">
        {{ selectedLowConfidenceIssues.length }} 条低于 85%，会保留待审
      </span>
    </div>

    <div v-if="loading" class="flex justify-center py-10 text-muted-foreground">
      <Loader2 :size="20" class="animate-spin" />
    </div>

    <div v-else-if="!issues.length" class="py-10 text-center text-sm text-muted-foreground">
      <ClipboardCheck :size="28" class="mx-auto mb-2 opacity-40" />
      {{ status === 'pending' ? '暂无待审批的聚合质量问题' : '暂无记录' }}
    </div>

    <div v-else class="space-y-2.5">
      <div
        v-for="(issue, issueIndex) in issues"
        :key="issue.id"
        :id="`quality-issue-${issue.id}`"
        class="rounded-lg border border-border bg-card p-3.5 transition-colors"
        :class="{
          'opacity-60': status !== 'pending',
          'border-primary ring-1 ring-primary/20': selectedIds.has(issue.id),
        }"
      >
        <div class="flex items-start justify-between gap-3">
          <Checkbox
            v-if="status === 'pending'"
            :model-value="selectedIds.has(issue.id)"
            :aria-label="`选择审查项：${issue.question}`"
            :disabled="busy || processing.has(issue.id)"
            class="mt-0.5"
            @click.stop.prevent="toggleIssueSelection(issue, issueIndex, $event)"
          />
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5 mb-1">
              <Badge :class="issueTypeColor(issue.issue_type)" class="text-[11px]">
                {{ issue.issue_type_label }}
              </Badge>
              <Badge variant="secondary" class="text-[11px]">
                {{ issue.action_label }}
              </Badge>
              <span class="text-[11px] text-muted-foreground">
                置信度 {{ (issue.confidence * 100).toFixed(0) }}%
              </span>
            </div>

            <!-- 前后对照：当前（代表题+面经原题） → 操作后（只显示被处理题） -->
            <div class="mt-2 grid grid-cols-[1fr_auto_1fr] items-stretch gap-2">
              <!-- 当前列：代表题 + 面经原题 -->
              <div class="min-w-0 rounded-md border border-border bg-muted/60 px-2.5 py-2">
                <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">当前</div>
                <div class="text-xs font-medium leading-snug">{{ issue.question }}</div>
                <div
                  v-if="issue.variant && issue.suggested_action !== 'refine_representative'"
                  class="mt-2 border-t border-border/70 pt-2"
                >
                  <div class="text-[10px] font-semibold text-destructive uppercase tracking-wide mb-0.5">面经原题</div>
                  <div class="text-[11px] text-destructive leading-snug">{{ issue.variant }}</div>
                </div>
              </div>
              <!-- 箭头 -->
              <div class="flex items-center justify-center text-muted-foreground">
                <ArrowRight :size="14" />
              </div>
              <!-- 操作后列：只显示被处理的那道题 -->
              <div class="min-w-0 rounded-md border border-primary/25 bg-primary/5 px-2.5 py-2">
                <div class="text-[10px] font-semibold text-primary uppercase tracking-wide mb-1">
                  {{ targetOf(issue).label }}
                </div>
                <div class="text-xs font-medium leading-snug">
                  {{ targetOf(issue).text }}
                </div>
                <!-- 分类变化：有变化才显示 -->
                <div
                  v-if="catChange(issue)"
                  class="mt-1.5 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary"
                >
                  {{ catChange(issue) }}
                </div>
                <!-- 换成规范代表题：展示面经原题，供判断改写质量 -->
                <div
                  v-if="issue.suggested_action === 'refine_representative' && issue.original_questions?.length"
                  class="mt-1.5 border-t border-primary/20 pt-1.5"
                >
                  <div class="text-[10px] font-semibold text-muted-foreground mb-0.5">面经原题（该聚类实际问过）</div>
                  <div v-for="(oq, oi) in issue.original_questions" :key="oi" class="text-[11px] text-muted-foreground leading-snug truncate">
                    · {{ oq }}
                  </div>
                </div>
              </div>
            </div>

            <div v-if="issue.reason" class="mt-1.5 text-xs text-muted-foreground">
              {{ issue.reason }}
            </div>
            <div v-if="status !== 'pending'" class="mt-1 text-[11px] text-muted-foreground">
              处理时间：{{ issue.reviewed_at || '—' }}
            </div>
          </div>

          <div v-if="status === 'pending'" class="flex shrink-0 flex-col gap-1.5">
            <Button
              variant="default"
              size="sm"
              class="h-7 gap-1 text-xs"
              :disabled="processing.has(issue.id)"
              @click="onApprove(issue)"
            >
              <Check :size="13" />
              批准
            </Button>
            <Button
              variant="outline"
              size="sm"
              class="h-7 gap-1 text-xs text-muted-foreground"
              :disabled="processing.has(issue.id)"
              @click="onReject(issue)"
            >
              <X :size="13" />
              拒绝
            </Button>
          </div>
          <ShieldCheck v-else-if="issue.status === 'done'" :size="16" class="shrink-0 text-green-500" />
          <ShieldX v-else :size="16" class="shrink-0 text-muted-foreground" />
        </div>
      </div>
    </div>
  </div>
</template>

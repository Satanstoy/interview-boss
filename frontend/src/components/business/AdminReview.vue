<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[9998] flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
        <div data-material="glass" class="rounded-xl border border-border shadow-lg w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col animate-slide-up overflow-hidden">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-border flex items-center justify-between bg-muted/40">
            <div class="flex items-center gap-3">
              <div class="size-9 rounded-xl bg-muted flex items-center justify-center">
                <svg class="size-5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <div>
                <h2 class="text-lg font-bold text-foreground">公共贡献审核</h2>
                <p class="text-xs text-muted-foreground mt-0.5">面经题库与 JD 使用同一审核入口，审核通过后才进入公共处理链路</p>
              </div>
            </div>
            <button aria-label="关闭" @click="$emit('close')" class="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition">
              <svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Content -->
          <div class="flex-1 overflow-y-auto custom-scrollbar px-6 py-4">
            <div class="flex gap-2 mb-4">
              <Button
                v-for="tab in sourceTabs"
                :key="tab.value"
                size="sm"
                :variant="sourceType === tab.value ? 'default' : 'outline'"
                @click="sourceType = tab.value"
              >{{ tab.label }}</Button>
            </div>
            <section v-if="reviewItem" class="mb-4 space-y-4 rounded-lg border border-border p-4">
              <div class="flex justify-between items-center">
                <h3 class="font-semibold">审核详情</h3>
                <Button variant="ghost" size="sm" @click="closeReview" :disabled="reviewBusy">返回列表</Button>
              </div>
              <p class="text-xs text-muted-foreground">{{ reviewItem.source_type === 'jd' ? 'JD 公司、来源和薪资需填写确认。' : '面经默认保留公司和轮次，可修改或清空；来源链接需填写确认。' }}请预览实际发布内容。</p>
              <div v-for="field in sourceFields" :key="field.key">
                <label :for="`review-source-${field.key}`" class="block text-sm mb-1">{{ field.label }}</label>
                <input :id="`review-source-${field.key}`" v-model="draft.source[field.key]" :disabled="reviewBusy || reviewItem.legacy" class="w-full rounded border border-border bg-background px-3 py-2 text-sm" />
              </div>
              <div v-for="(item, index) in draft.items" :key="item.item_id" class="space-y-2 rounded border border-border p-3">
                <label v-if="!reviewItem.legacy" class="flex gap-2 items-center text-sm">
                  <input v-model="item.excluded" type="checkbox" :aria-label="`排除题目 ${index + 1}`" :disabled="reviewBusy" />排除题目 {{ index + 1 }}
                </label>
                <label :for="`review-question-${index}`" class="block text-sm">题干 {{ index + 1 }}</label>
                <textarea :id="`review-question-${index}`" v-model="item.question" :disabled="reviewBusy || reviewItem.legacy" class="w-full rounded border border-border bg-background px-3 py-2 text-sm" />
                <div v-for="field in itemFields" :key="field.key">
                  <label :for="`review-${field.key}-${index}`" class="block text-sm">{{ field.label }} {{ index + 1 }}</label>
                  <input :id="`review-${field.key}-${index}`" v-model="item[field.key]" :disabled="reviewBusy || reviewItem.legacy" class="w-full rounded border border-border bg-background px-3 py-2 text-sm" />
                </div>
              </div>
              <p v-if="reviewItem.legacy" class="text-sm text-muted-foreground">历史单题沿用提交的题干与分类；私人来源及私人模型答案不公开。</p>
              <p v-if="reviewError" data-testid="review-error" class="text-sm text-destructive">{{ reviewError }}</p>
              <Button v-if="reviewConflict" variant="outline" size="sm" @click="openReview(reviewItem)" :disabled="reviewBusy">重新读取详情（替换当前编辑）</Button>
              <div class="flex gap-2">
                <Button @click="previewReview" :disabled="reviewBusy || reviewConflict">预览公开内容</Button>
                <Button @click="confirmReview" :disabled="reviewBusy || !preview || reviewConflict" class="bg-emerald-500 text-white">确认通过</Button>
              </div>
              <div v-if="preview" data-testid="review-projection-preview" class="rounded border border-border p-3 text-sm">
                <h4 class="font-semibold mb-2">实际公开内容</h4>
                <p v-for="(value, key) in preview.source" :key="key">{{ sourceLabel(key) }}：{{ value || '不公开 / 暂缺' }}</p>
                <div v-for="item in preview.items" :key="item.item_id" class="mt-3 border-t border-border pt-2">
                  <p>{{ item.question }}</p>
                  <p v-for="original in originalQuestions(item)" :key="original" class="mt-1 text-muted-foreground">原题：{{ original }}</p>
                  <p>{{ item.cat1 }} / {{ item.cat2 }} · {{ item.difficulty }} · {{ Array.isArray(item.tags) ? item.tags.join('、') : item.tags }}</p>
                </div>
              </div>
            </section>
            <!-- Loading -->
            <div v-if="loading" class="flex flex-col items-center justify-center py-16 gap-3">
              <svg class="animate-spin h-6 w-6 text-primary-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              <span class="text-muted-foreground text-sm">加载中...</span>
            </div>

            <!-- Empty -->
            <div v-else-if="items.length === 0" class="text-center py-16">
              <div class="size-16 mx-auto mb-4 rounded-xl bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                <svg class="size-8 text-emerald-500 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <p class="text-foreground font-medium">暂无待审核贡献</p>
              <p class="text-sm text-muted-foreground mt-1">当前筛选范围内没有面经题库或 JD 申请</p>
            </div>

            <!-- List -->
            <div v-else v-auto-animate class="flex flex-col gap-3">
              <div
                v-for="item in items"
                :key="item.legacy ? `legacy-${item.id}` : `contribution-${item.id}`"
                :data-review-key="reviewKey(item)"
                class="border border-border rounded-xl p-4 hover:border-primary/30 hover:shadow-sm transition-all duration-200 animate-fade-in"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                      <Badge variant="outline">{{ item.source_type === 'jd' ? 'JD' : '题库' }}</Badge>
                      <span class="text-xs text-muted-foreground">申请 #{{ item.id }}</span>
                    </div>
                    <p class="text-sm font-medium text-foreground leading-relaxed">
                      {{ item.summary?.company || '未提供公司' }}
                      <span v-if="item.summary?.round"> · {{ item.summary.round }}</span>
                      <span v-if="item.summary?.job_title"> · {{ item.summary.job_title }}</span>
                    </p>
                    <p class="text-xs text-muted-foreground mt-1">
                      {{ item.source_type === 'jd' ? '整份 JD' : `${item.summary?.item_count || 0} 道题目` }}
                    </p>
                    <div v-if="item.summary?.question_previews?.length" class="mt-2 space-y-1">
                      <p v-for="(preview, index) in item.summary.question_previews" :key="`${item.id}-${index}`" class="text-xs text-muted-foreground leading-relaxed">
                        {{ index + 1 }}. {{ preview.question }}
                      </p>
                    </div>
                    <p v-if="item.legacy" class="text-xs text-amber-600 dark:text-amber-400 mt-2">历史单题申请</p>
                    <div class="flex flex-wrap gap-1.5 mt-2.5">
                      <Badge v-if="item.cat1" variant="outline" class="bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-100 dark:border-primary-800/50">{{ item.cat1 }}</Badge>
                      <Badge v-if="item.difficulty" variant="outline" class="bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-400 border-accent-100 dark:border-accent-800/50">{{ item.difficulty }}</Badge>
                      <Badge v-if="item.submitted_by_name" variant="outline" class="bg-muted text-muted-foreground">{{ item.submitted_by_name }}</Badge>
                    </div>
                  </div>
                  <div class="flex gap-2 shrink-0">
                    <Button
                      @click="openReview(item)"
                      :disabled="reviewBusy || processingIds.has(reviewKey(item))"
                      size="sm"
                      class="bg-emerald-500 text-white hover:bg-emerald-600"
                    >通过</Button>
                    <Button
                      @click="handleReject(item)"
                      :disabled="reviewBusy || processingIds.has(reviewKey(item))"
                      variant="destructive"
                      size="sm"
                    >拒绝</Button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-3.5 border-t border-border flex justify-between items-center bg-muted/40">
            <span class="text-sm text-muted-foreground">共 <span class="font-bold text-foreground">{{ items.length }}</span> 条待审核</span>
            <Button @click="loadPending" variant="ghost" size="sm" class="text-primary-600 dark:text-primary-400">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              刷新
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { fetchPublicContributions, fetchPublicContribution, previewPublicContribution, approvePublicContribution, rejectPublicContribution, previewPendingQuestion, approveQuestion, rejectQuestion } from '@/api/index.js'
import { useToast } from '@/composables/useNotification.js'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close', 'reviewed'])
const { success, error: showError } = useToast()

const loading = ref(false)
const items = ref([])
const processingIds = ref(new Set())
const sourceType = ref('')
const sourceTabs = [
  { value: '', label: '全部' },
  { value: 'interview', label: '题库' },
  { value: 'jd', label: 'JD' },
]

watch(() => props.visible, (v) => { if (v) loadPending() })
watch(sourceType, () => { if (props.visible) loadPending() })

async function loadPending() {
  loading.value = true
  try {
    const data = await fetchPublicContributions({ sourceType: sourceType.value })
    items.value = data.items || []
  } catch (e) {
    showError('加载公共贡献失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

function reviewKey(item) {
  return `${item.legacy ? 'legacy' : 'contribution'}-${item.id}`
}

const reviewItem = ref(null)
const reviewBusy = ref(false)
const reviewError = ref('')
const reviewConflict = ref(false)
const revision = ref(null)
const draft = ref({ source: {}, items: [] })
const preview = ref(null)
let previewPayload = null
let reviewGeneration = 0
const fieldLabels = { company: '公开公司', round: '公开轮次', source_url: '公开来源 URL', focus: '公开考察重点', difficulty: '公开难度', season: '公开招聘季', job_title: '公开岗位名称', tech_stack: '公开技术栈', bonus: '公开加分项', position: '公开职位', salary: '公开薪资' }
const sourceFields = computed(() => (reviewItem.value?.legacy ? [] : reviewItem.value?.source_type === 'jd'
  ? ['company', 'job_title', 'tech_stack', 'bonus', 'position', 'salary', 'source_url']
  : ['company', 'round', 'focus', 'difficulty', 'season', 'source_url']).map(key => ({ key, label: fieldLabels[key] })))
const itemFields = [{ key: 'cat1', label: '一级分类' }, { key: 'cat2', label: '二级分类' }, { key: 'tags', label: '标签（逗号分隔）' }, { key: 'difficulty', label: '难度' }]
const sourceLabel = key => fieldLabels[key] || key
function originalQuestions(item) {
  try { return JSON.parse(item.original_questions || '[]') } catch { return [] }
}
watch(draft, () => { preview.value = null; previewPayload = null; reviewGeneration++ }, { deep: true, flush: 'sync' })
watch(() => props.visible, visible => { if (!visible) closeReview() })

function closeReview() {
  reviewGeneration++
  reviewItem.value = null
  preview.value = null
  previewPayload = null
  reviewError.value = ''
  reviewConflict.value = false
}

async function openReview(item) {
  const generation = ++reviewGeneration
  reviewBusy.value = true
  reviewError.value = ''
  reviewConflict.value = false
  preview.value = null
  previewPayload = null
  try {
    const detail = item.legacy ? await previewPendingQuestion(item.id) : await fetchPublicContribution(item.id)
    if (generation !== reviewGeneration) return
    if (!item.legacy && (!Number.isInteger(detail.revision) || detail.revision < 1)) throw new Error('审核详情缺少有效版本，请重新加载')
    reviewItem.value = item
    revision.value = detail.revision
    const source = detail.snapshot?.source || {}
    const fields = item.legacy ? [] : item.source_type === 'jd'
      ? ['company', 'job_title', 'tech_stack', 'bonus', 'position', 'salary', 'source_url']
      : ['company', 'round', 'focus', 'difficulty', 'season', 'source_url']
    const confirmationFields = item.source_type === 'jd'
      ? ['company', 'salary', 'source_url']
      : ['source_url']
    draft.value = {
      source: Object.fromEntries(fields.map(key => [key, confirmationFields.includes(key) ? '' : source[key] ?? ''])),
      items: (item.legacy ? [{ id: item.id, snapshot: detail.projection }] : item.source_type === 'jd' ? [] : detail.items || []).map(row => ({
        item_id: row.id, question: row.snapshot?.question || '', cat1: row.snapshot?.cat1 || '', cat2: row.snapshot?.cat2 || '',
        tags: Array.isArray(row.snapshot?.tags) ? row.snapshot.tags.join(', ') : row.snapshot?.tags || '', difficulty: row.snapshot?.difficulty || '', excluded: false,
      })),
    }
  } catch (error) {
    reviewError.value = error.message || '读取审核详情失败'
    showError(reviewError.value)
  } finally { reviewBusy.value = false }
}

function reviewPayload() {
  return {
    expected_revision: revision.value,
    excluded_item_ids: draft.value.items.filter(item => item.excluded).map(item => item.item_id),
    review_fields: {
      source: Object.fromEntries(Object.entries(draft.value.source).map(([key, value]) => [key, String(value).trim() || null])),
      items: draft.value.items.map(({ item_id, question, cat1, cat2, difficulty, tags }) => ({ item_id, question, cat1, cat2, difficulty, tags: tags.split(/[,，]/).map(tag => tag.trim()).filter(Boolean) })),
    },
  }
}

async function previewReview() {
  reviewBusy.value = true
  reviewError.value = ''
  const generation = reviewGeneration
  try {
    const payload = reviewPayload()
    const result = reviewItem.value.legacy
      ? await previewPendingQuestion(reviewItem.value.id)
      : await previewPublicContribution(reviewItem.value.id, payload)
    if (generation !== reviewGeneration) return
    preview.value = reviewItem.value.legacy ? { source: {}, items: [{ item_id: reviewItem.value.id, ...result.projection }] } : result.projection
    previewPayload = payload
  } catch (error) {
    reviewError.value = error.message || '预览失败'
    if (error.status === 409) reviewConflict.value = true
  } finally { reviewBusy.value = false }
}

async function confirmReview() {
  if (!reviewItem.value || !preview.value || !previewPayload || reviewConflict.value) return
  const item = reviewItem.value
  const key = reviewKey(item)
  reviewBusy.value = true
  reviewError.value = ''
  try {
    if (item.legacy) await approveQuestion(item.id)
    else await approvePublicContribution(item.id, previewPayload)
    items.value = items.value.filter(row => reviewKey(row) !== key)
    closeReview()
    success('已通过审核')
    emit('reviewed')
  } catch (error) {
    reviewError.value = error.message || '审核失败'
    if (error.status === 409) reviewConflict.value = true
    showError(reviewError.value)
  } finally { reviewBusy.value = false }
}

async function handleReject(item) {
  const id = item.id
  const key = reviewKey(item)
  processingIds.value = new Set(processingIds.value).add(key)
  try {
    if (item?.legacy) await rejectQuestion(id)
    else await rejectPublicContribution(id)
    items.value = items.value.filter(i => reviewKey(i) !== key)
    success('已拒绝')
    emit('reviewed')
  } catch (e) {
    showError('操作失败: ' + (e.message || '未知错误'))
  } finally {
    const next = new Set(processingIds.value)
    next.delete(key)
    processingIds.value = next
  }
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>

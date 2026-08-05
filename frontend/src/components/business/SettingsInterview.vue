<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { CalendarClock } from '@lucide/vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { switchMyPosition, deletePosition, createPosition, generateTaxonomy, confirmTaxonomy, fetchPositions, fetchRecruitmentPref, updateRecruitmentPref } from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import AppTooltip from '@/components/common/AppTooltip.vue'
import InterviewDistributionSettings from '@/components/business/InterviewDistributionSettings.vue'

const props = defineProps({
  masterBank: { type: Array, default: () => [] },
})

const emit = defineEmits(['go-to-question', 'profile-updated'])
const { success: toastSuccess, error: toastError, warning: toastWarning } = useToast()
const { confirm: showConfirm } = useConfirm()

const { displayUser, currentUser } = inject('appData')

onMounted(async () => {
  try {
    const data = await fetchPositions()
    positions.value = data.positions || []
    // 从用户数据初始化当前岗位
    if (displayUser.value?.current_position) {
      currentPosition.value = displayUser.value.current_position
    }
  } catch (e) {
    console.error('Failed to fetch positions', e)
  }
  loadRecruitmentPref()
})

// ── Recruitment time preference ──
const YEAR_OPTIONS = Array.from({ length: 2035 - 2024 + 1 }, (_, i) => String(2024 + i))
const BATCH_OPTIONS = [
  { value: '__none__', label: '暂不参加校招' },
  { value: 'daily', label: '日常实习' },
  { value: 'summer_intern', label: '暑期实习' },
  { value: 'autumn', label: '秋招' },
  { value: 'spring', label: '春招' },
]

const graduationYear = ref(null)
const batch = ref('__none__')
const dailyCapacity = ref(30)
const timeline = ref([])
const savingPref = ref(false)

const loadRecruitmentPref = async () => {
  try {
    const data = await fetchRecruitmentPref()
    graduationYear.value = data.graduation_year ? String(data.graduation_year) : null
    batch.value = data.batch || '__none__'
    dailyCapacity.value = data.daily_capacity || 30
    timeline.value = data.milestones || []
  } catch (e) {
    console.error('Failed to fetch recruitment pref', e)
  }
}

const daysFromNow = (dateStr) => {
  const target = new Date(`${dateStr}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((target.getTime() - today.getTime()) / 86_400_000)
  return diff >= 0 ? `${diff} 天后` : `已过 ${-diff} 天`
}

const savePref = async () => {
  savingPref.value = true
  try {
    const payload = {
      graduation_year: graduationYear.value ? Number(graduationYear.value) : null,
      batch: batch.value === '__none__' ? '' : batch.value,
      daily_capacity: Number(dailyCapacity.value) || 30,
    }
    const data = await updateRecruitmentPref(payload)
    timeline.value = data.milestones || []
    toastSuccess('面试时间偏好已保存')
  } catch (e) {
    toastError('保存失败，请稍后重试')
  } finally {
    savingPref.value = false
  }
}

// ── Position management ──
const positions = ref([])
const currentPosition = ref('')
const newPositionInput = ref('')
const switching = ref(false)

const setCurrentPosition = (pos) => {
  currentPosition.value = pos
}

const handleSwitchPosition = async (pos) => {
  if (pos === currentPosition.value) return
  switching.value = true
  try {
    const data = await switchMyPosition(pos)
    currentPosition.value = pos
    if (currentUser?.value) {
      currentUser.value = {
        ...currentUser.value,
        current_position: data.current_position || data.current_job_position || pos,
        current_position_id: data.current_position_id ?? null,
      }
    }
    toastSuccess(`已切换到岗位：${pos}`)
    emit('profile-updated')
  } catch (e) {
    toastError(`切换失败: ${e.message}`)
  } finally {
    switching.value = false
  }
}

const handleAddPosition = async () => {
  const name = newPositionInput.value.trim()
  if (!name) return
  if (name.length > 30) {
    toastWarning('岗位名称不能超过 30 个字符')
    return
  }
  if (positions.value.some(p => p.name === name)) {
    toastWarning('该岗位已存在')
    return
  }
  try {
    await createPosition(name)
    // 添加到本地列表
    positions.value.push({ name })
    newPositionInput.value = ''
    toastSuccess(`岗位「${name}」已添加`)
    emit('profile-updated')
  } catch (e) {
    toastError(`添加失败: ${e.message}`)
  }
}

const handleDeletePosition = async (pos) => {
  if (!await showConfirm(`确定要删除岗位"${pos}"吗？`)) return
  try {
    await deletePosition(pos)
    // 从本地列表中移除（positions 是对象数组，按 name 匹配）
    positions.value = positions.value.filter(p => p.name !== pos)
    if (currentPosition.value === pos) {
      currentPosition.value = ''
    }
    toastSuccess(`岗位"${pos}"已删除`)
    emit('profile-updated')
  } catch (e) {
    toastError(`删除失败: ${e.message}`)
  }
}

// ── AI Taxonomy suggestion ──
const taxonomyLoading = ref(false)
const taxonomyPreview = ref(null) // { position, categories }
const taxonomyOpen = ref(false)

const handleGenerateTaxonomy = async () => {
  if (!currentPosition.value) {
    toastWarning('请先选择目标岗位')
    return
  }
  taxonomyLoading.value = true
  try {
    const data = await generateTaxonomy()
    taxonomyPreview.value = data
    taxonomyOpen.value = true
  } catch (e) {
    toastError(`AI生成失败: ${e.message}`)
  } finally {
    taxonomyLoading.value = false
  }
}

const handleConfirmTaxonomy = async () => {
  if (!taxonomyPreview.value) return
  try {
    await confirmTaxonomy(taxonomyPreview.value.categories)
    taxonomyOpen.value = false
    taxonomyPreview.value = null
    toastSuccess('分类体系已更新')
    emit('profile-updated')
  } catch (e) {
    toastError(`保存失败: ${e.message}`)
  }
}

const handleCancelTaxonomy = () => {
  taxonomyOpen.value = false
  taxonomyPreview.value = null
}

// ── Favorites ──
const starredQuestions = computed(() => {
  return props.masterBank
    .filter(q => q.is_starred)
    .slice(0, 20)
})

const handleGoToQuestion = (question) => {
  emit('go-to-question', question)
}
</script>

<template>
  <div class="w-full space-y-8">
    <div>
      <h3 class="text-lg font-semibold text-foreground">面试偏好</h3>
      <p class="text-sm text-muted-foreground mt-1">设置你的目标岗位和面试偏好</p>
    </div>

    <!-- Card 1: 目标岗位 -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <h4 class="text-sm font-semibold text-foreground">目标岗位</h4>

      <!-- Position button group -->
      <div class="flex gap-2 flex-wrap">
        <div v-for="pos in positions" :key="pos.id || pos.name" class="flex items-center gap-1">
          <Button
            :variant="currentPosition === pos.name ? 'default' : 'outline'"
            size="sm"
            :disabled="switching"
            @click="handleSwitchPosition(pos.name)"
            :class="currentPosition === pos.name
              ? 'bg-primary/10 text-primary border-primary/30 hover:bg-primary/15'
              : ''"
          >
            {{ pos.name }}
          </Button>
          <AppTooltip text="删除岗位">
            <Button
              variant="ghost"
              size="icon-sm"
              @click="handleDeletePosition(pos.name)"
              class="text-muted-foreground/50 hover:text-destructive transition-colors"
            >
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </Button>
          </AppTooltip>
        </div>
      </div>

      <!-- Add new position -->
      <div class="flex gap-2">
        <Input
          v-model="newPositionInput"
          placeholder="新增岗位（最多30字）"
          class="flex-1 text-sm"
          @keyup.enter="handleAddPosition"
        />
        <Button variant="outline" size="sm" @click="handleAddPosition" class="whitespace-nowrap">
          添加
        </Button>
      </div>
      <div v-if="newPositionInput.length > 20" class="text-xs" :class="newPositionInput.length > 30 ? 'text-destructive' : 'text-muted-foreground'">
        {{ newPositionInput.length }} / 30
      </div>

      <!-- AI Taxonomy button -->
      <Button
        @click="handleGenerateTaxonomy"
        :disabled="taxonomyLoading || !currentPosition"
        variant="outline"
        size="sm"
        class="w-full"
      >
        <svg v-if="taxonomyLoading" class="size-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        <svg v-else class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        {{ taxonomyLoading ? 'AI 生成中...' : 'AI 推荐分类体系' }}
      </Button>
    </div>

    <InterviewDistributionSettings :job-position="currentPosition" @saved="() => toastSuccess('面试分布已保存')" />

    <!-- Card 2: 收藏夹 -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <h4 class="text-sm font-semibold text-foreground">收藏夹</h4>

      <div v-if="starredQuestions.length === 0" class="text-sm text-muted-foreground py-4 text-center">
        暂无收藏题目
      </div>

      <div v-else class="flex flex-col gap-2">
        <div
          v-for="question in starredQuestions"
          :key="question.id"
          class="flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-accent/50 cursor-pointer transition-colors"
          @click="handleGoToQuestion(question)"
        >
          <svg class="size-4 text-amber-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
          </svg>
          <span class="text-sm text-foreground truncate flex-1">{{ question.question }}</span>
          <svg class="size-4 text-muted-foreground shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </div>
    </div>

    <!-- Card 3: 面试时间偏好 -->
    <div class="rounded-xl border bg-card p-6 space-y-4">
      <div class="flex items-center gap-2">
        <CalendarClock class="size-4 text-muted-foreground" />
        <h4 class="text-sm font-semibold text-foreground">面试时间偏好</h4>
      </div>
      <p class="text-xs text-muted-foreground">选择你的招聘季和每日复习容量，系统将据此自动安排每天的复习题量和新题比例（影响「今日复习」队列）</p>

      <div class="flex flex-col gap-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <div class="space-y-2">
            <Label class="text-sm font-medium text-foreground">届次</Label>
            <Select :model-value="graduationYear || undefined" @update:model-value="graduationYear = $event || null">
              <SelectTrigger class="w-full text-sm">
                <SelectValue placeholder="选择届次" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="y in YEAR_OPTIONS" :key="y" :value="y">{{ y }} 届</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-2">
            <Label class="text-sm font-medium text-foreground">招聘批次</Label>
            <Select :model-value="batch" @update:model-value="batch = $event">
              <SelectTrigger class="w-full text-sm">
                <SelectValue placeholder="选择批次" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in BATCH_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div class="space-y-2">
          <Label class="text-sm font-medium text-foreground">每日容量</Label>
          <Input v-model.number="dailyCapacity" type="number" min="5" max="200" class="max-w-40 text-sm" />
          <p class="text-xs text-muted-foreground">每天计划复习的题目数量（5 - 200）</p>
        </div>

        <div v-if="timeline.length > 0" class="rounded-lg border border-border bg-muted/50 p-3 flex flex-col gap-1.5">
          <div v-for="m in timeline" :key="m.name" class="text-xs text-muted-foreground">
            {{ m.name }} {{ m.date }}（{{ daysFromNow(m.date) }}）
          </div>
        </div>

        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Button :disabled="savingPref" @click="savePref" class="sm:w-auto">
            {{ savingPref ? '保存中...' : '保存' }}
          </Button>
          <p class="text-xs text-muted-foreground">将根据距最近里程碑的天数自动调整每日复习题量和新题比例，越临近窗口关闭复习越密集</p>
        </div>
      </div>
    </div>

    <!-- AI Taxonomy Preview Dialog -->
    <Dialog :open="taxonomyOpen" @update:open="handleCancelTaxonomy">
      <DialogContent class="sm:max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>AI 推荐分类体系</DialogTitle>
          <DialogDescription>岗位：{{ taxonomyPreview?.position }}</DialogDescription>
        </DialogHeader>
        <div class="flex-1 overflow-y-auto flex flex-col gap-3">
          <div v-for="(cat, i) in (taxonomyPreview?.categories || [])" :key="i" class="rounded-xl border border-border overflow-hidden">
            <div class="px-4 py-2.5 bg-primary/10 dark:bg-primary/20 font-semibold text-sm text-primary">
              {{ cat.cat1 }}
            </div>
            <div class="px-4 py-2 flex flex-col gap-1">
              <div v-for="(child, j) in cat.children" :key="j" class="text-sm text-muted-foreground pl-4">
                {{ child }}
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="handleCancelTaxonomy">取消</Button>
          <Button @click="handleConfirmTaxonomy">采纳此分类</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

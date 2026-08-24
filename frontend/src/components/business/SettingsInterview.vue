<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { CalendarClock } from '@lucide/vue'
import { useToast } from '@/composables/useNotification.js'
import { switchMyPosition, fetchPositions, fetchRecruitmentPref, updateRecruitmentPref } from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import InterviewDistributionSettings from '@/components/business/InterviewDistributionSettings.vue'

const props = defineProps({
  masterBank: { type: Array, default: () => [] },
})

const emit = defineEmits(['go-to-question', 'profile-updated'])
const { success: toastSuccess, error: toastError } = useToast()

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
const pace = ref('standard')
const timeline = ref([])
const savingPref = ref(false)

const PACE_OPTIONS = [
  { value: 'easy', label: '轻松', desc: '降低复习强度，间隔拉长' },
  { value: 'standard', label: '标准', desc: '按招聘季节奏自动安排' },
  { value: 'hard', label: '冲刺', desc: '加密复习间隔，优先到期题' },
]

const loadRecruitmentPref = async () => {
  try {
    const data = await fetchRecruitmentPref()
    graduationYear.value = data.graduation_year ? String(data.graduation_year) : null
    batch.value = data.batch || '__none__'
    dailyCapacity.value = data.daily_capacity || 30
    pace.value = data.pace || 'standard'
    timeline.value = data.windows || []
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
      pace: pace.value,
    }
    const data = await updateRecruitmentPref(payload)
    timeline.value = data.windows || []
    toastSuccess('面试时间偏好已保存')
  } catch {
    toastError('保存失败，请稍后重试')
  } finally {
    savingPref.value = false
  }
}

// ── Position management ──
const positions = ref([])
const currentPosition = ref('')
const switching = ref(false)

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
        <div v-for="pos in positions" :key="pos.id || pos.name">
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
        </div>
      </div>

      <p class="text-xs text-muted-foreground">
        岗位分类由系统统一维护，用于个人题库、公共题库、JD 和面经的统一聚类；你可以在题库中使用个人标签和练习分组进行个性化整理。
      </p>
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

        <div class="space-y-2">
          <Label class="text-sm font-medium text-foreground">复习节奏</Label>
          <div class="flex gap-2">
            <button
              v-for="opt in PACE_OPTIONS"
              :key="opt.value"
              type="button"
              :class="['h-9 flex-1 rounded-md border px-2 text-xs transition-colors',
                       pace === opt.value
                         ? 'border-primary bg-primary/10 text-primary font-medium'
                         : 'border-border text-muted-foreground hover:bg-muted']"
              :data-testid="`pace-${opt.value}`"
              @click="pace = opt.value"
            >
              {{ opt.label }}
            </button>
          </div>
          <p class="text-xs text-muted-foreground">{{ PACE_OPTIONS.find(o => o.value === pace)?.desc }}</p>
        </div>

        <div v-if="timeline.length > 0" class="rounded-lg border border-border bg-muted/50 p-3 flex flex-col gap-1.5">
          <div v-for="w in timeline" :key="w.name" class="text-xs text-muted-foreground">
            {{ w.name }}高峰 {{ w.peak }}（{{ daysFromNow(w.peak) }}）
          </div>
        </div>

        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Button :disabled="savingPref" @click="savePref" class="sm:w-auto">
            {{ savingPref ? '保存中...' : '保存' }}
          </Button>
          <p class="text-xs text-muted-foreground">系统按招聘季窗口自动安排每天的复习题量和新题比例，临近窗口高峰复习越密集；节奏档位可随时调整</p>
        </div>
      </div>
    </div>

  </div>
</template>

<template>
  <div data-testid="practice-view" class="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
    <div v-if="recruitmentStatus.graduation_year" data-testid="recruitment-status" class="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border bg-card px-4 py-2 text-xs text-muted-foreground">
      <CalendarClock class="size-3.5" />
      <template v-if="recruitmentStatus.current_window">
        <span class="font-medium text-foreground">{{ recruitmentStatus.current_window.name }}窗口</span>
        <Badge variant="secondary" class="text-[10px]">{{ stageLabel }}</Badge>
      </template>
      <template v-else-if="recruitmentStatus.next_window">
        <span>距{{ recruitmentStatus.next_window.name }}高峰还有 {{ recruitmentStatus.next_window.days_left }} 天</span>
        <Badge variant="secondary" class="text-[10px]">{{ stageLabel }}</Badge>
      </template>
      <span v-else>持续准备中</span>
      <span class="ml-auto">{{ windowsLabel }} · 容量 {{ recruitmentStatus.daily_capacity }} 题{{ paceLabel }}</span>
    </div>
    <PracticeMode
      :questions="practiceQuestions"
      :practiced-questions="practicedQuestions"
      :decks="decks"
      :selected-deck-key="selectedDeckKey"
      :selected-deck="selectedDeck"
      :review-loading="isReviewing"
      :deck-loading="isLoading"
      :has-more-questions="serverReady && hasMoreQuestions"
      :question-total="serverReady ? questionTotal : practiceQuestions.length"
      :loading-more-questions="isLoadingMoreQuestions"
      :daily-capacity="recruitmentStatus.daily_capacity"
      :capacity-saving="capacitySaving"
      :resume-scope="currentUser?.id || currentUser?.username || 'anonymous'"
      :is-admin="currentUser?.is_admin"
      class="w-full min-w-0"
      @close="closePractice"
      @select-deck="selectDeck"
      @load-more="loadMoreQuestions"
      @review="handleReview"
      @correct-review="handleCorrectReview"
      @update-daily-capacity="handleUpdateDailyCapacity"
      @toggle-star="toggleStar"
      @manage-decks="openDeckManager"
      @add-to-deck="addQuestionToDeck"
    />
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, inject, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CalendarClock } from '@lucide/vue'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/composables/useNotification.js'
import { fetchRecruitmentPref, updateRecruitmentPref } from '@/services/profileApi.js'

const PracticeMode = defineAsyncComponent({
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/PracticeMode.vue'),
})

const router = useRouter()
const toast = useToast()
const { filteredMasterBank, practicedQuestions, toggleStar, currentUser } = inject('appData')
const {
  decks, questions: deckQuestions, selectedDeckKey, selectedDeck, isLoading, isReviewing, serverReady,
  questionTotal, hasMoreQuestions, isLoadingMoreQuestions, loadQuestions, invalidateQuestions, loadMoreQuestions, submitReview, correctReview, addItem,
} = inject('practiceDecks')
const practiceQuestions = computed(() => serverReady.value ? deckQuestions.value : filteredMasterBank.value)

const recruitmentStatus = ref({
  graduation_year: null, batch: '', daily_capacity: 30, pace: 'standard',
  windows: [], current_window: null, next_window: null, urgency: 0,
})
const capacitySaving = ref(false)

const stageLabel = computed(() => {
  const urgency = recruitmentStatus.value.urgency ?? 0
  if (urgency >= 0.7) return '攻坚中'
  if (urgency >= 0.3) return '冲刺中'
  if (urgency > 0) return '准备中'
  return '从容复习'
})

const windowsLabel = computed(() => {
  const windows = recruitmentStatus.value.windows || []
  if (windows.length === 0) return '社招模式'
  return `${windows[0]?.name}等 ${windows.length} 个窗口`
})

const paceLabel = computed(() => ({
  easy: ' · 轻松',
  hard: ' · 冲刺',
})[recruitmentStatus.value.pace] || '')

onMounted(async () => {
  try {
    recruitmentStatus.value = await fetchRecruitmentPref()
  } catch {
    // 使用默认值
  }
})

const closePractice = () => router.push('/master-bank')
const openDeckManager = () => router.push('/practice/decks')
async function selectDeck(deckKey) {
  await loadQuestions(deckKey)
  await router.replace({ path: '/practice', query: { deck: deckKey } })
}
async function addQuestionToDeck({ deckKey, questionId }) {
  if (await addItem(deckKey, questionId)) {
    if (selectedDeckKey.value === deckKey) await loadQuestions(deckKey)
  }
}
async function handleReview(payload) {
  const response = await submitReview(payload)
  payload.onComplete?.(response)
}
async function handleCorrectReview(payload) {
  const response = await correctReview(payload)
  payload.onComplete?.(response)
}
async function handleUpdateDailyCapacity(value) {
  const dailyCapacity = Math.min(200, Math.max(5, Number(value) || 30))
  if (capacitySaving.value || dailyCapacity === recruitmentStatus.value.daily_capacity) return
  const previousCapacity = recruitmentStatus.value.daily_capacity
  capacitySaving.value = true
  try {
    recruitmentStatus.value = await updateRecruitmentPref({
      graduation_year: recruitmentStatus.value.graduation_year,
      batch: recruitmentStatus.value.batch,
      daily_capacity: dailyCapacity,
      pace: recruitmentStatus.value.pace,
    })
    invalidateQuestions('due')
    const queue = await loadQuestions('due')
    if (!queue) {
      toast.warning('每日计划已保存，题目刷新失败，请重新进入刷题页')
    } else if (dailyCapacity > previousCapacity && !(queue.items || []).length) {
      toast.info('每日计划已调整，题库里暂时没有更多新题')
    } else {
      toast.success(`每日计划已调整为 ${dailyCapacity} 题`)
    }
  } catch {
    toast.error('每日计划调整失败，请稍后重试')
  } finally {
    capacitySaving.value = false
  }
}
</script>

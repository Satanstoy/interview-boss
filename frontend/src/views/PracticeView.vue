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
      :review-loading="isReviewing"
      :deck-loading="isLoading"
      :has-more-questions="serverReady && hasMoreQuestions"
      :question-total="serverReady ? questionTotal : practiceQuestions.length"
      :loading-more-questions="isLoadingMoreQuestions"
      :is-admin="currentUser?.is_admin"
      class="w-full min-w-0"
      @close="closePractice"
      @select-deck="selectDeck"
      @load-more="loadMoreQuestions"
      @review="handleReview"
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
import { fetchRecruitmentPref } from '@/services/profileApi.js'

const PracticeMode = defineAsyncComponent({
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/PracticeMode.vue'),
})

const router = useRouter()
const { filteredMasterBank, practicedQuestions, toggleStar, currentUser } = inject('appData')
const {
  decks, questions: deckQuestions, selectedDeckKey, isLoading, isReviewing, serverReady,
  questionTotal, hasMoreQuestions, isLoadingMoreQuestions, loadQuestions, loadMoreQuestions, submitReview, addItem,
} = inject('practiceDecks')
const practiceQuestions = computed(() => serverReady.value ? deckQuestions.value : filteredMasterBank.value)

const recruitmentStatus = ref({
  graduation_year: null, batch: '', daily_capacity: 30, pace: 'standard',
  windows: [], current_window: null, next_window: null, urgency: 0,
})

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
</script>

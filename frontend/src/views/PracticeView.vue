<template>
  <div data-testid="practice-view" class="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
    <div v-if="recruitmentStatus.batch" data-testid="recruitment-status" class="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-border bg-card px-4 py-2 text-xs text-muted-foreground">
      <CalendarClock class="size-3.5" />
      <template v-if="recruitmentStatus.next_milestone">
        <span class="font-medium text-foreground">距{{ recruitmentStatus.next_milestone.name }}还有 {{ recruitmentStatus.days_left }} 天</span>
        <Badge variant="secondary" class="text-[10px]">{{ stageLabel }}</Badge>
      </template>
      <span v-else>未设置面试时间偏好，使用默认复习节奏</span>
      <span class="ml-auto">{{ batchLabel }} · 每日容量 {{ recruitmentStatus.daily_capacity }} 题</span>
    </div>
    <PracticeMode
      :questions="practiceQuestions"
      :practiced-questions="practicedQuestions"
      :decks="decks"
      :selected-deck-key="selectedDeckKey"
      :review-loading="isReviewing"
      :deck-loading="isLoading"
      :is-admin="currentUser?.is_admin"
      class="w-full min-w-0"
      @close="closePractice"
      @select-deck="selectDeck"
      @review="submitReview"
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
  loadQuestions, submitReview, addItem,
} = inject('practiceDecks')
const practiceQuestions = computed(() => serverReady.value ? deckQuestions.value : filteredMasterBank.value)

const recruitmentStatus = ref({ batch: '', next_milestone: null, days_left: null, daily_capacity: 30 })

const stageLabel = computed(() => {
  const urgency = recruitmentStatus.value.urgency ?? 0
  if (urgency >= 0.7) return '攻坚中'
  if (urgency >= 0.3) return '冲刺中'
  if (urgency > 0) return '准备中'
  return '从容复习'
})

const batchLabel = computed(() => ({
  daily: '日常实习',
  summer_intern: '暑期实习',
  autumn: '秋招',
  spring: '春招',
})[recruitmentStatus.value.batch] || '')

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
</script>

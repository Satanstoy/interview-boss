<template>
  <div data-testid="practice-view" class="flex h-full min-h-0 min-w-0 flex-1 overflow-hidden">
    <PracticeMode
      :questions="practiceQuestions"
      :practiced-questions="practicedQuestions"
      :decks="decks"
      :selected-deck-key="selectedDeckKey"
      :review-loading="isReviewing"
      :deck-loading="isLoading"
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
import { computed, defineAsyncComponent, inject } from 'vue'
import { useRouter } from 'vue-router'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const PracticeMode = defineAsyncComponent({
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/PracticeMode.vue'),
})

const router = useRouter()
const { filteredMasterBank, practicedQuestions, toggleStar } = inject('appData')
const {
  decks, questions: deckQuestions, selectedDeckKey, isLoading, isReviewing, serverReady,
  loadQuestions, submitReview, addItem,
} = inject('practiceDecks')
const practiceQuestions = computed(() => serverReady.value ? deckQuestions.value : filteredMasterBank.value)

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

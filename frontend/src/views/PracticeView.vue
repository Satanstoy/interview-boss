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
      @select-deck="loadQuestions"
      @review="submitReview"
      @toggle-star="toggleStar"
      @manage-decks="openDeckManager"
    />
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, inject, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AsyncLoading from '@/components/common/AsyncLoading.vue'
import { usePracticeDecks } from '@/composables/usePracticeDecks.js'

const PracticeMode = defineAsyncComponent({
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/PracticeMode.vue'),
})

const router = useRouter()
const route = useRoute()
const { filteredMasterBank, practicedQuestions, bankFilter, toggleStar } = inject('appData')
const {
  decks, questions: deckQuestions, selectedDeckKey, isLoading, isReviewing, serverReady,
  loadDecks, loadQuestions, submitReview,
} = usePracticeDecks(bankFilter)
const practiceQuestions = computed(() => serverReady.value ? deckQuestions.value : filteredMasterBank.value)

onMounted(async () => {
  await loadDecks()
  if (serverReady.value) {
    const requestedDeck = String(route.query.deck || '')
    const initialDeck = requestedDeck && decks.value.some(deck => deck.key === requestedDeck)
      ? requestedDeck
      : selectedDeckKey.value
    await loadQuestions(initialDeck)
  }
})
const closePractice = () => router.push('/master-bank')
const openDeckManager = () => router.push('/practice/decks')
</script>

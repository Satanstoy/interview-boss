<template>
  <PracticeDeckManager
    :decks="decks"
    :available-questions="filteredMasterBank"
    :selected-questions="questions"
    :selected-deck-key="selectedDeckKey"
    :loading="isLoading"
    @select-deck="loadManagerDeck"
    @start-deck="startDeck"
    @create-deck="createManagerDeck"
    @update-deck="updateManagerDeck"
    @delete-deck="deleteManagerDeck"
    @add-item="addManagerItem"
    @remove-item="removeManagerItem"
  />
</template>

<script setup>
import { defineAsyncComponent, inject } from 'vue'
import { useRouter } from 'vue-router'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const PracticeDeckManager = defineAsyncComponent({
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/PracticeDeckManager.vue'),
})

const router = useRouter()
const { filteredMasterBank } = inject('appData')
const {
  decks, questions, selectedDeckKey, isLoading, loadQuestions,
  createDeck, updateDeck, deleteDeck, addItem, removeItem,
} = inject('practiceDecks')

async function loadManagerDeck(deckKey) {
  await loadQuestions(deckKey)
}
function startDeck(deckKey) {
  router.push({ path: '/practice', query: { deck: deckKey } })
}
async function createManagerDeck(payload) {
  await createDeck(payload)
}
async function updateManagerDeck({ deckKey, payload }) {
  await updateDeck(deckKey, payload)
}
async function deleteManagerDeck(deckKey) {
  if (!window.confirm('确定删除这个自定义题单吗？题目和刷题记录不会被删除。')) return
  await deleteDeck(deckKey)
  if (selectedDeckKey.value === deckKey) questions.value = []
}
async function addManagerItem({ deckKey, questionId }) {
  if (await addItem(deckKey, questionId)) await loadQuestions(deckKey)
}
async function removeManagerItem({ deckKey, questionId }) {
  if (await removeItem(deckKey, questionId)) await loadQuestions(deckKey)
}

</script>

import { computed, ref, unref } from 'vue'
import * as api from '@/api/index.js'
import { getFriendlyError } from '@/services/http.js'
import { useToast } from './useNotification.js'

/** Loads named study plans and owns the server-backed review queue. */
export function usePracticeDecks(filter = 'all') {
  const toast = useToast()
  const decks = ref([])
  const questions = ref([])
  const selectedDeckKey = ref('all')
  const selectedDeck = ref(null)
  const isLoading = ref(false)
  const isReviewing = ref(false)
  const serverReady = ref(false)
  const error = ref(null)

  const selectedDeckSummary = computed(() => selectedDeck.value || decks.value.find(deck => deck.key === selectedDeckKey.value) || null)

  async function loadDecks() {
    try {
      const response = await api.fetchPracticeDecks({ filter: unref(filter) })
      serverReady.value = true
      decks.value = response.items || []
      if (!decks.value.some(deck => deck.key === selectedDeckKey.value)) selectedDeckKey.value = decks.value[0]?.key || 'all'
    } catch (err) {
      error.value = getFriendlyError(err, '题单加载失败')
      toast.error(error.value)
    }
  }

  async function loadQuestions(deckKey = selectedDeckKey.value) {
    selectedDeckKey.value = deckKey
    isLoading.value = true
    error.value = null
    try {
      const response = await api.fetchPracticeDeckQuestions(deckKey, { filter: unref(filter), limit: 100 })
      questions.value = response.items || []
      selectedDeck.value = response.deck || decks.value.find(deck => deck.key === deckKey) || null
      return response
    } catch (err) {
      error.value = getFriendlyError(err, '题单加载失败')
      toast.error(error.value)
      questions.value = []
      return null
    } finally { isLoading.value = false }
  }

  async function submitReview({ questionId, rating, score = null }) {
    isReviewing.value = true
    try {
      const response = await api.submitPracticeReview({ question_id: questionId, rating, score })
      const nextState = response.review || {}
      const item = questions.value.find(question => question.id === questionId)
      if (item) Object.assign(item, nextState)
      const deck = decks.value.find(candidate => candidate.key === selectedDeckKey.value)
      if (deck) {
        deck.reviewed = Number(deck.reviewed || 0) + (item?.review_count === 1 ? 1 : 0)
        deck.progress = deck.total ? Math.round(deck.reviewed / deck.total * 100) : 0
      }
      return response
    } catch (err) {
      toast.error(getFriendlyError(err, '复习记录保存失败'))
      return null
    } finally { isReviewing.value = false }
  }

  async function createDeck(payload) {
    try {
      const deck = await api.createPracticeDeck(payload)
      await loadDecks()
      return deck
    } catch (err) {
      toast.error(getFriendlyError(err, '创建题单失败'))
      return null
    }
  }

  async function updateDeck(deckKey, payload) {
    try {
      const deck = await api.updatePracticeDeck(deckKey, payload)
      await loadDecks()
      return deck
    } catch (err) {
      toast.error(getFriendlyError(err, '保存题单失败'))
      return null
    }
  }

  async function deleteDeck(deckKey) {
    try {
      await api.deletePracticeDeck(deckKey)
      if (selectedDeckKey.value === deckKey) {
        selectedDeckKey.value = decks.value.find(deck => deck.key !== deckKey)?.key || 'all'
        await loadQuestions(selectedDeckKey.value)
      }
      await loadDecks()
      return true
    } catch (err) {
      toast.error(getFriendlyError(err, '删除题单失败'))
      return false
    }
  }

  async function addItem(deckKey, questionId) {
    try {
      await api.addPracticeDeckItem(deckKey, questionId)
      return true
    } catch (err) {
      toast.error(getFriendlyError(err, '加入题单失败'))
      return false
    }
  }

  async function removeItem(deckKey, questionId) {
    try {
      await api.removePracticeDeckItem(deckKey, questionId)
      return true
    } catch (err) {
      toast.error(getFriendlyError(err, '移出题单失败'))
      return false
    }
  }

  return {
    decks,
    questions,
    selectedDeckKey,
    selectedDeck: selectedDeckSummary,
    isLoading,
    isReviewing,
    serverReady,
    error,
    loadDecks,
    loadQuestions,
    submitReview,
    createDeck,
    updateDeck,
    deleteDeck,
    addItem,
    removeItem,
  }
}

import { computed, ref, unref } from 'vue'
import * as api from '@/api/index.js'
import { getFriendlyError } from '@/services/http.js'
import { useToast, useConfirm } from './useNotification.js'

/** Loads named study plans and owns the server-backed review queue. */
export function usePracticeDecks(filter = 'all') {
  const toast = useToast()
  const { confirm: showConfirm } = useConfirm()
  const decks = ref([])
  const questions = ref([])
  const selectedDeckKey = ref('due')
  const selectedDeck = ref(null)
  const isLoading = ref(false)
  const isReviewing = ref(false)
  const serverReady = ref(false)
  const error = ref(null)
  const loadedDeckKey = ref(null)
  const questionCache = new Map()

  const selectedDeckSummary = computed(() => selectedDeck.value || decks.value.find(deck => deck.key === selectedDeckKey.value) || null)

  async function loadDecks() {
    try {
      const response = await api.fetchPracticeDecks({ filter: unref(filter) })
      serverReady.value = true
      decks.value = response.items || []
      if (!decks.value.some(deck => deck.key === selectedDeckKey.value)) {
        const dueDeck = decks.value.find(deck => deck.key === 'due')
        selectedDeckKey.value = dueDeck ? 'due' : (decks.value[0]?.key || 'all')
      }
    } catch (err) {
      error.value = getFriendlyError(err, '题单加载失败')
      toast.error(error.value)
    }
  }

  async function loadQuestions(deckKey = selectedDeckKey.value) {
    selectedDeckKey.value = deckKey
    isLoading.value = true
    error.value = null
    const cacheKey = `${unref(filter)}:${deckKey}`
    const cached = questionCache.get(cacheKey)
    if (cached) {
      questions.value = cached.items || []
      selectedDeck.value = cached.deck || decks.value.find(deck => deck.key === deckKey) || null
      loadedDeckKey.value = deckKey
      isLoading.value = false
      return cached
    }
    try {
      const response = await api.fetchPracticeDeckQuestions(deckKey, { filter: unref(filter), limit: 100 })
      questionCache.set(cacheKey, response)
      questions.value = response.items || []
      selectedDeck.value = response.deck || decks.value.find(deck => deck.key === deckKey) || null
      loadedDeckKey.value = deckKey
      return response
    } catch (err) {
      error.value = getFriendlyError(err, '题单加载失败')
      toast.error(error.value)
      questions.value = []
      loadedDeckKey.value = null
      return null
    } finally { isLoading.value = false }
  }

  async function submitReview({ questionId, rating, score = null }) {
    isReviewing.value = true
    try {
      const response = await api.submitPracticeReview({ question_id: questionId, rating, score })
      const nextState = response.review || {}
      const item = questions.value.find(question => question.id === questionId)
      if (selectedDeckKey.value === 'due' && nextState.next_review_at) {
        // next_review_at 是服务器 UTC naive 时间（YYYY-MM-DD HH:MM:SS）→ 按 UTC 解析后取本地日期比较
        const nextDate = new Date(String(nextState.next_review_at).replace(' ', 'T') + 'Z')
        if (!Number.isNaN(nextDate.getTime())) {
          const todayStr = new Date().toLocaleDateString('en-CA')
          const nextDateStr = nextDate.toLocaleDateString('en-CA')
          if (nextDateStr > todayStr) {
            // 替换数组而非 splice：原地变更不会让 deckQuestions → practiceQuestions → sessionQuestions
            // 计算链失效，PracticeMode 的索引补偿 watch 将不会触发，导致复习后跳过下一张卡
            questions.value = questions.value.filter(question => question.id !== questionId)
          }
        }
      }
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
      questionCache.clear()
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
      questionCache.delete(`${unref(filter)}:${deckKey}`)
      await loadDecks()
      return deck
    } catch (err) {
      toast.error(getFriendlyError(err, '保存题单失败'))
      return null
    }
  }

  async function deleteDeck(deckKey) {
    const deck = decks.value.find(d => d.key === deckKey)
    const deckName = deck?.label || deckKey
    if (!await showConfirm(`确定要删除题单「${deckName}」吗？题单内的题目不会被删除。`, { title: '确认删除', variant: 'danger' })) return false
    try {
      await api.deletePracticeDeck(deckKey)
      questionCache.delete(`${unref(filter)}:${deckKey}`)
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
      questionCache.delete(`${unref(filter)}:${deckKey}`)
      return true
    } catch (err) {
      toast.error(getFriendlyError(err, '加入题单失败'))
      return false
    }
  }

  async function removeItem(deckKey, questionId) {
    try {
      await api.removePracticeDeckItem(deckKey, questionId)
      questionCache.delete(`${unref(filter)}:${deckKey}`)
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
    loadedDeckKey,
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

import { computed, ref, unref } from 'vue'
import * as api from '@/api/index.js'
import { getFriendlyError } from '@/services/http.js'
import { useToast, useConfirm } from './useNotification.js'

/** Loads named study plans and owns the server-backed review queue. */
export function usePracticeDecks(filter = 'all') {
  const QUESTION_PAGE_SIZE = 100
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
  const questionTotal = ref(0)
  const isLoadingMoreQuestions = ref(false)
  const questionCache = new Map()

  // 今日复习的 items 可能因为每日新题容量少于 total，这是有意设计，不能
  // 用普通分页把被容量策略排除的新题重新加载回来。
  const hasMoreQuestions = computed(() => (
    selectedDeckKey.value !== 'due' && questions.value.length < questionTotal.value
  ))

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
      questionTotal.value = Number(cached.total ?? questions.value.length)
      selectedDeck.value = cached.deck || decks.value.find(deck => deck.key === deckKey) || null
      loadedDeckKey.value = deckKey
      isLoading.value = false
      return cached
    }
    try {
      const response = await api.fetchPracticeDeckQuestions(deckKey, {
        filter: unref(filter), limit: QUESTION_PAGE_SIZE, offset: 0,
      })
      questionCache.set(cacheKey, response)
      questions.value = response.items || []
      questionTotal.value = Number(response.total ?? questions.value.length)
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

  async function loadMoreQuestions(deckKey = selectedDeckKey.value) {
    if (
      deckKey === 'due'
      || isLoadingMoreQuestions.value
      || deckKey !== selectedDeckKey.value
      || !hasMoreQuestions.value
    ) return null

    const cacheKey = `${unref(filter)}:${deckKey}`
    const cached = questionCache.get(cacheKey)
    const currentItems = cached?.items || questions.value
    const total = Number(cached?.total ?? questionTotal.value ?? currentItems.length)
    if (currentItems.length >= total) return cached || null

    isLoadingMoreQuestions.value = true
    try {
      const response = await api.fetchPracticeDeckQuestions(deckKey, {
        filter: unref(filter),
        limit: QUESTION_PAGE_SIZE,
        offset: currentItems.length,
      })
      const seenIds = new Set(currentItems.map(item => item.id))
      const nextItems = [
        ...currentItems,
        ...(response.items || []).filter(item => !seenIds.has(item.id)),
      ]
      const mergedResponse = {
        ...response,
        items: nextItems,
        total: Number(response.total ?? total),
        page_size: QUESTION_PAGE_SIZE,
        offset: 0,
      }
      questionCache.set(cacheKey, mergedResponse)
      // 如果切换题单发生在请求期间，不要把旧题单的结果写进当前队列；缓存仍然保留，
      // 下次切回该题单时可以直接使用。
      if (deckKey === selectedDeckKey.value) {
        questionTotal.value = mergedResponse.total
        questions.value = nextItems
        selectedDeck.value = response.deck || selectedDeck.value
      }
      return mergedResponse
    } catch (err) {
      toast.error(getFriendlyError(err, '加载更多题目失败'))
      return null
    } finally {
      isLoadingMoreQuestions.value = false
    }
  }

  async function submitReview({ questionId, rating, score = null }) {
    isReviewing.value = true
    try {
      const response = await api.submitPracticeReview({ question_id: questionId, rating, score })
      const nextState = response.review || {}
      const item = questions.value.find(question => question.id === questionId)
      // 同一道题可能同时存在于今日复习、全部题、收藏和自定义题单缓存中。
      // 选择评分后立即同步所有缓存；是否暂时保留当前卡供用户核对答案，由
      // PracticeMode 控制。这样退出再进入时也不会从已完成的旧卡重新开始。
      for (const cached of questionCache.values()) {
        const cachedItem = cached?.items?.find(question => question.id === questionId)
        if (cachedItem) Object.assign(cachedItem, nextState)
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
    questionTotal,
    hasMoreQuestions,
    isLoadingMoreQuestions,
    serverReady,
    error,
    loadDecks,
    loadQuestions,
    loadMoreQuestions,
    submitReview,
    createDeck,
    updateDeck,
    deleteDeck,
    addItem,
    removeItem,
  }
}

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
  let reviewedDueQueueIds = new Set()

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
    // 今日复习是随时间和每次评分变化的活队列：重新进入时必须向服务器确认，
    // 否则刚完成的题或刚到期的重学题会被永久缓存住。普通题单仍复用缓存。
    if (cached && deckKey !== 'due') {
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
      if (deckKey === 'due') reviewedDueQueueIds = new Set()
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
    const reviewedDeckKey = selectedDeckKey.value
    const reviewedDeck = selectedDeck.value
    const item = questions.value.find(question => question.id === questionId)
    const wasReviewedToday = isUtcToday(item?.last_reviewed_at)
    const wasPracticed = Number(item?.review_count || 0) > 0
    const previousNextReviewAt = item?.next_review_at || null
    const queueKind = !previousNextReviewAt
      ? 'new_question_count'
      : (item?.is_checkin ? 'checkin_count' : 'due_review_count')
    const queueReviewIds = reviewedDueQueueIds
    const wasReviewedInQueue = queueReviewIds.has(questionId)
    try {
      const response = await api.submitPracticeReview({ question_id: questionId, rating, score })
      const nextState = response.review || {}
      // 同一道题可能同时存在于今日复习、全部题、收藏和自定义题单缓存中。
      // 选择评分后立即同步所有缓存；是否暂时保留当前卡供用户核对答案，由
      // PracticeMode 控制。这样退出再进入时也不会从已完成的旧卡重新开始。
      for (const cached of questionCache.values()) {
        const cachedItem = cached?.items?.find(question => question.id === questionId)
        if (cachedItem) Object.assign(cachedItem, nextState)
      }
      if (item) Object.assign(item, nextState)
      if (reviewedDeckKey === 'due' && reviewedDeck) {
        if (!wasReviewedToday && !wasReviewedInQueue) {
          reviewedDeck.completed_today = Number(reviewedDeck.completed_today || 0) + 1
        }
        if (!wasReviewedInQueue) {
          reviewedDeck.remaining_today = Math.max(0, Number(reviewedDeck.remaining_today ?? questions.value.length) - 1)
          reviewedDeck[queueKind] = Math.max(0, Number(reviewedDeck[queueKind] || 0) - 1)
          queueReviewIds.add(questionId)
        }
        if (!reviewedDeck.studied_today) {
          reviewedDeck.studied_today = true
          reviewedDeck.study_streak = Number(reviewedDeck.study_streak || 0) + 1
          reviewedDeck.longest_streak = Math.max(
            Number(reviewedDeck.longest_streak || 0),
            reviewedDeck.study_streak,
          )
        }
        reviewedDeck.planned_today = Number(reviewedDeck.completed_today || 0) + Number(reviewedDeck.remaining_today || 0)
        if (nextState.next_review_at) {
          const currentNextDue = reviewedDeck.next_due_at
          if (!currentNextDue || String(nextState.next_review_at) < String(currentNextDue)) {
            reviewedDeck.next_due_at = nextState.next_review_at
          }
        }
        adjustReviewForecast(reviewedDeck, previousNextReviewAt, nextState.next_review_at)
      }
      const deck = decks.value.find(candidate => candidate.key === reviewedDeckKey)
      if (deck) {
        deck.reviewed = Number(deck.reviewed || 0) + (wasPracticed ? 0 : 1)
        deck.progress = deck.total ? Math.round(deck.reviewed / deck.total * 100) : 0
      }
      return response
    } catch (err) {
      toast.error(getFriendlyError(err, '复习记录保存失败'))
      return null
    } finally { isReviewing.value = false }
  }

  async function correctReview({ eventId, questionId, rating, score = null }) {
    isReviewing.value = true
    const reviewedDeckKey = selectedDeckKey.value
    const reviewedDeck = selectedDeck.value
    const item = questions.value.find(question => question.id === questionId)
    const previousNextReviewAt = item?.next_review_at || null
    try {
      const response = await api.correctPracticeReview(eventId, { rating, score })
      const nextState = response.review || {}
      for (const cached of questionCache.values()) {
        const cachedItem = cached?.items?.find(question => question.id === questionId)
        if (cachedItem) Object.assign(cachedItem, nextState)
      }
      if (item) Object.assign(item, nextState)
      if (reviewedDeckKey === 'due' && reviewedDeck) {
        adjustReviewForecast(reviewedDeck, previousNextReviewAt, nextState.next_review_at)
      }
      return response
    } catch (err) {
      toast.error(getFriendlyError(err, '修正自评失败'))
      return null
    } finally {
      isReviewing.value = false
    }
  }

  function isUtcToday(value) {
    if (!value) return false
    const raw = String(value)
    const parsed = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw)
      ? raw
      : `${raw.replace(' ', 'T')}Z`)
    if (Number.isNaN(parsed.getTime())) return false
    return parsed.toISOString().slice(0, 10) === new Date().toISOString().slice(0, 10)
  }

  function utcDateKey(value) {
    if (!value) return ''
    const raw = String(value)
    const parsed = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw)
      ? raw
      : `${raw.replace(' ', 'T')}Z`)
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString().slice(0, 10)
  }

  function adjustReviewForecast(deck, previousDate, nextDate) {
    if (!Array.isArray(deck?.review_forecast)) return
    const previousKey = utcDateKey(previousDate)
    const nextKey = utcDateKey(nextDate)
    deck.review_forecast = deck.review_forecast.map(day => {
      let count = Number(day.count || 0)
      if (previousKey && day.date === previousKey) count = Math.max(0, count - 1)
      if (nextKey && day.date === nextKey) count += 1
      return { ...day, count }
    })
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
    correctReview,
    createDeck,
    updateDeck,
    deleteDeck,
    addItem,
    removeItem,
  }
}

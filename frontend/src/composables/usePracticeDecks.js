import { computed, ref, unref } from 'vue'
import * as api from '@/api/index.js'
import { getFriendlyError } from '@/services/http.js'
import { useToast, useConfirm } from './useNotification.js'

/** Loads named study plans and owns the server-backed review queue. */
export function usePracticeDecks(filter = 'all') {
  const QUESTION_PAGE_SIZE = 100
  const DUE_CACHE_TTL_MS = 60 * 1000
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
  const questionCacheUpdatedAt = new Map()
  const questionRefreshes = new Map()
  const questionRefreshModes = new Map()
  const questionRequestVersions = new Map()
  let activeLoadingRequest = null
  let reviewMutationVersion = 0
  let reviewedDueQueueIds = new Set()
  let attemptedDueQueueIds = new Set()

  // 今日复习的 items 可能因为每日新题容量少于 total，这是有意设计，不能
  // 用普通分页把被容量策略排除的新题重新加载回来。
  const hasMoreQuestions = computed(() => (
    selectedDeckKey.value !== 'due' && questions.value.length < questionTotal.value
  ))

  const selectedDeckSummary = computed(() => selectedDeck.value || decks.value.find(deck => deck.key === selectedDeckKey.value) || null)
  const INVALIDATED_RESPONSE = Symbol('invalidated-practice-response')

  function applyQuestionResponse(response, deckKey) {
    questions.value = response.items || []
    questionTotal.value = Number(response.total ?? questions.value.length)
    selectedDeck.value = response.deck || decks.value.find(deck => deck.key === deckKey) || null
    loadedDeckKey.value = deckKey
    if (deckKey === 'due') {
      reviewedDueQueueIds = new Set((response.items || [])
        .filter(question => isStudyDayToday(question.last_reviewed_at) && ['good', 'easy'].includes(question.last_rating))
        .map(question => question.id))
      attemptedDueQueueIds = new Set((response.items || [])
        .filter(question => isStudyDayToday(question.last_reviewed_at))
        .map(question => question.id))
    }
  }

  async function refreshQuestions(deckKey, cacheKey, { background = false, force = false } = {}) {
    const existingRefresh = questionRefreshes.get(cacheKey)
    if (!force && existingRefresh) {
      const mode = questionRefreshModes.get(cacheKey)
      if (mode && !mode.background) {
        activeLoadingRequest = mode.loadingRequest
        isLoading.value = true
      }
      return existingRefresh
    }

    const requestVersion = (questionRequestVersions.get(cacheKey) || 0) + 1
    questionRequestVersions.set(cacheKey, requestVersion)
    const mutationVersion = reviewMutationVersion
    const loadingRequest = `${cacheKey}:${requestVersion}`
    const request = (async () => {
      if (!background) {
        activeLoadingRequest = loadingRequest
        isLoading.value = true
      }
      try {
        const response = await api.fetchPracticeDeckQuestions(deckKey, {
          filter: unref(filter), limit: QUESTION_PAGE_SIZE, offset: 0,
        })
        // A review submitted while this request was in flight already updated the
        // local queue. Do not let an older server snapshot put the reviewed card back.
        if (questionRequestVersions.get(cacheKey) !== requestVersion) return INVALIDATED_RESPONSE
        if (reviewMutationVersion !== mutationVersion) return response

        questionCache.set(cacheKey, response)
        questionCacheUpdatedAt.set(cacheKey, Date.now())
        if (deckKey === selectedDeckKey.value) applyQuestionResponse(response, deckKey)
        return response
      } catch (err) {
        if (!background) {
          error.value = getFriendlyError(err, '题单加载失败')
          toast.error(error.value)
          questions.value = []
          loadedDeckKey.value = null
        }
        return null
      } finally {
        if (!background && activeLoadingRequest === loadingRequest) {
          activeLoadingRequest = null
          isLoading.value = false
        }
      }
    })()
    questionRefreshes.set(cacheKey, request)
    questionRefreshModes.set(cacheKey, { background, loadingRequest })
    try {
      const response = await request
      if (response === INVALIDATED_RESPONSE) {
        return refreshQuestions(deckKey, cacheKey, { background, force: true })
      }
      return response
    } finally {
      if (questionRefreshes.get(cacheKey) === request) {
        questionRefreshes.delete(cacheKey)
        questionRefreshModes.delete(cacheKey)
      }
    }
  }

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
    error.value = null
    const cacheKey = `${unref(filter)}:${deckKey}`
    const cached = questionCache.get(cacheKey)
    if (cached) {
      // Cache-first keeps the last usable queue visible while a stale due queue
      // is refreshed. The server remains authoritative; this only changes when
      // the refresh is allowed to block rendering.
      applyQuestionResponse(cached, deckKey)
      isLoading.value = false
      if (
        deckKey !== 'due'
        || Date.now() - (questionCacheUpdatedAt.get(cacheKey) || 0) < DUE_CACHE_TTL_MS
      ) return cached

      void refreshQuestions(deckKey, cacheKey, { background: true })
      return cached
    }
    return refreshQuestions(deckKey, cacheKey)
  }

  function invalidateQuestions(deckKey = null) {
    const keys = deckKey
      ? [`${unref(filter)}:${deckKey}`]
      : [...new Set([
          ...questionCache.keys(),
          ...questionCacheUpdatedAt.keys(),
          ...questionRefreshes.keys(),
        ])]
    for (const cacheKey of keys) {
      questionCache.delete(cacheKey)
      questionCacheUpdatedAt.delete(cacheKey)
      questionRequestVersions.set(cacheKey, (questionRequestVersions.get(cacheKey) || 0) + 1)
    }
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

    const requestVersion = questionRequestVersions.get(cacheKey) || 0
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
      if (questionRequestVersions.get(cacheKey) !== requestVersion) return questionCache.get(cacheKey) || null
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
    reviewMutationVersion += 1
    isReviewing.value = true
    const reviewedDeckKey = selectedDeckKey.value
    const reviewedDeck = selectedDeck.value
    const item = questions.value.find(question => question.id === questionId)
    const wasPassedToday = isStudyDayToday(item?.last_reviewed_at) && ['good', 'easy'].includes(item?.last_rating)
    const wasDailyRelearning = Boolean(item?.is_daily_relearning)
    const wasPracticed = Number(item?.review_count || 0) > 0
    const previousNextReviewAt = item?.next_review_at || null
    const originalQueueKind = !previousNextReviewAt
      ? 'new_question_count'
      : (item?.is_checkin ? 'checkin_count' : 'due_review_count')
    const queueKind = wasDailyRelearning ? 'relearning_count' : originalQueueKind
    const queueReviewIds = reviewedDueQueueIds
    const wasReviewedInQueue = queueReviewIds.has(questionId)
    try {
      const response = await api.submitPracticeReview({ question_id: questionId, rating, score })
      const nextState = response.review || {}
      // 同一道题可能同时存在于今日复习、全部题、收藏和自定义题单缓存中。
      // 选择评分后立即同步所有缓存；是否暂时保留当前卡供用户核对答案，由
      // PracticeMode 控制。这样退出再进入时也不会从已完成的旧卡重新开始。
      for (const [cacheKey, cached] of questionCache.entries()) {
        const cachedItem = cached?.items?.find(question => question.id === questionId)
        if (cachedItem) {
          Object.assign(cachedItem, nextState)
          questionCacheUpdatedAt.set(cacheKey, Date.now())
        }
      }
      if (item) Object.assign(item, nextState)
      if (reviewedDeckKey === 'due' && reviewedDeck) {
        const passedNow = nextState.passed_today ?? ['good', 'easy'].includes(rating)
        reviewedDeck.review_attempts_today = Number(reviewedDeck.review_attempts_today || 0) + 1
        if (!attemptedDueQueueIds.has(questionId)) {
          reviewedDeck.attempted_today = Number(reviewedDeck.attempted_today || 0) + 1
          attemptedDueQueueIds.add(questionId)
        }
        if (!passedNow && !wasDailyRelearning) {
          reviewedDeck[originalQueueKind] = Math.max(0, Number(reviewedDeck[originalQueueKind] || 0) - 1)
          reviewedDeck.relearning_count = Number(reviewedDeck.relearning_count || 0) + 1
        }
        if (passedNow && !wasPassedToday && !wasReviewedInQueue) {
          reviewedDeck.completed_today = Number(reviewedDeck.completed_today || 0) + 1
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
        if (passedNow) adjustReviewForecast(reviewedDeck, previousNextReviewAt, nextState.next_review_at)
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

  async function correctReview({ eventId, questionId, rating, previousRating = null, score = null }) {
    reviewMutationVersion += 1
    isReviewing.value = true
    const reviewedDeckKey = selectedDeckKey.value
    const reviewedDeck = selectedDeck.value
    const item = questions.value.find(question => question.id === questionId)
    const wasPassedToday = previousRating
      ? ['good', 'easy'].includes(previousRating)
      : (isStudyDayToday(item?.last_reviewed_at) && ['good', 'easy'].includes(item?.last_rating))
    const previousNextReviewAt = item?.next_review_at || null
    try {
      const response = await api.correctPracticeReview(eventId, { rating, score })
      const nextState = response.review || {}
      for (const [cacheKey, cached] of questionCache.entries()) {
        const cachedItem = cached?.items?.find(question => question.id === questionId)
        if (cachedItem) {
          Object.assign(cachedItem, nextState)
          questionCacheUpdatedAt.set(cacheKey, Date.now())
        }
      }
      if (item) Object.assign(item, nextState)
      if (reviewedDeckKey === 'due' && reviewedDeck) {
        const passedNow = nextState.passed_today ?? ['good', 'easy'].includes(rating)
        if (wasPassedToday !== passedNow) {
          const delta = passedNow ? 1 : -1
          reviewedDeck.completed_today = Math.max(0, Number(reviewedDeck.completed_today || 0) + delta)
          reviewedDeck.remaining_today = Math.max(0, Number(reviewedDeck.remaining_today || 0) - delta)
          reviewedDeck.relearning_count = Math.max(0, Number(reviewedDeck.relearning_count || 0) - delta)
          if (passedNow) reviewedDueQueueIds.add(questionId)
          else reviewedDueQueueIds.delete(questionId)
          reviewedDeck.planned_today = Number(reviewedDeck.completed_today || 0) + Number(reviewedDeck.remaining_today || 0)
        }
        if (wasPassedToday && !passedNow) {
          adjustReviewForecast(reviewedDeck, previousNextReviewAt, null)
        } else if (!wasPassedToday && passedNow) {
          adjustReviewForecast(reviewedDeck, null, nextState.next_review_at)
        } else if (passedNow) {
          adjustReviewForecast(reviewedDeck, previousNextReviewAt, nextState.next_review_at)
        }
      }
      return response
    } catch (err) {
      toast.error(getFriendlyError(err, '修正自评失败'))
      return null
    } finally {
      isReviewing.value = false
    }
  }

  function isStudyDayToday(value) {
    if (!value) return false
    const raw = String(value)
    const parsed = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw)
      ? raw
      : `${raw.replace(' ', 'T')}Z`)
    if (Number.isNaN(parsed.getTime())) return false
    const now = new Date()
    return parsed.getFullYear() === now.getFullYear()
      && parsed.getMonth() === now.getMonth()
      && parsed.getDate() === now.getDate()
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
      invalidateQuestions()
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
      invalidateQuestions(deckKey)
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
      invalidateQuestions(deckKey)
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
      invalidateQuestions(deckKey)
      return true
    } catch (err) {
      toast.error(getFriendlyError(err, '加入题单失败'))
      return false
    }
  }

  async function removeItem(deckKey, questionId) {
    try {
      await api.removePracticeDeckItem(deckKey, questionId)
      invalidateQuestions(deckKey)
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
    invalidateQuestions,
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

/**
 * useMasterBankData — 题库数据获取 + 筛选
 *
 * 职责：jdData/interviewData/masterBank 的获取、缓存失效、
 *       标签/难度/搜索/招聘季等过滤逻辑、analytic s/practiceStats
 * 不负责：认证、selection、UI 模态框状态
 */
import { ref, computed, watch } from 'vue'
import { invalidateCache, getFriendlyError } from '@/services/http.js'
import * as api from '@/api/index.js'

export function useMasterBankData({ onAfterFetch } = {}) {
  // ── Core data ──
  const jdData = ref([])
  const interviewData = ref([])
  const masterBank = ref([])
  const isDataLoading = ref(false)
  const dataLoadError = ref(null)
  const analytics = ref({ tech_trends: {} })
  const popularTagsFromServer = ref([])
  const practiceStats = ref({})
  const activeSeason = ref('')
  const availableSeasons = ref([])

  // ── Infinite scroll pagination ──
  const PAGE_SIZE = 30
  const currentPage = ref(1)
  const hasMore = ref(true)
  const isLoadingMore = ref(false)

  // ── Filters ──
  const selectedTag = ref('全部')
  const selectedSubTags = ref([])
  const searchQuery = ref('')
  const filterDifficulty = ref('')
  const showStarredOnly = ref(false)
  const filterSeason = ref('')
  const interviewSortOrder = ref('desc')

  // ── Data fetching ──
  const fetchTableData = async () => {
    isDataLoading.value = true
    dataLoadError.value = null
    invalidateCache()
    currentPage.value = 1
    hasMore.value = true
    try {
      const [jdResp, intResp, masterResp] = await Promise.all([
        api.fetchJdData(), api.fetchInterviewData(), api.fetchMasterBank({ page: 1, page_size: PAGE_SIZE, cat1: selectedTag.value !== '全部' ? selectedTag.value : undefined })
      ])
      jdData.value = (jdResp.items || jdResp).map(item => ({ ...item }))
      interviewData.value = (intResp.items || intResp).map(item => ({ ...item }))
      const items = (masterResp.items || masterResp).map(q => ({
        ...q, _showAnswer: false, _showSources: false,
        _isLoadingAnswer: false, _isRetagging: false, _isEditingAnswer: false, _editAnswer: ''
      }))
      masterBank.value = items
      // 检查是否还有更多数据
      const total = masterResp.total || 0
      hasMore.value = items.length < total
      currentPage.value = 1
      if (masterResp.popular_tags) { popularTagsFromServer.value = masterResp.popular_tags }
      selectedSubTags.value = []
      onAfterFetch?.()
    } catch (e) {
      dataLoadError.value = getFriendlyError(e, '数据加载失败，请刷新重试')
    } finally { isDataLoading.value = false }
  }

  /** 加载下一页题库数据（无限滚动） */
  const loadMoreMasterBank = async () => {
    if (isLoadingMore.value || !hasMore.value) return
    isLoadingMore.value = true
    try {
      const nextPage = currentPage.value + 1
      const resp = await api.fetchMasterBank({ page: nextPage, page_size: PAGE_SIZE, cat1: selectedTag.value !== '全部' ? selectedTag.value : undefined })
      const newItems = (resp.items || resp).map(q => ({
        ...q, _showAnswer: false, _showSources: false,
        _isLoadingAnswer: false, _isRetagging: false, _isEditingAnswer: false, _editAnswer: ''
      }))
      if (newItems.length > 0) {
        masterBank.value = [...masterBank.value, ...newItems]
        currentPage.value = nextPage
      }
      const total = resp.total || 0
      hasMore.value = masterBank.value.length < total
    } catch (e) {
      console.warn('加载更多题目失败', e)
    } finally { isLoadingMore.value = false }
  }

  const fetchAnalytics = async () => {
    try { analytics.value = await api.fetchAnalytics() } catch (e) { console.warn('获取分析数据失败', e) }
  }
  const fetchPracticeStats = async () => {
    try { practiceStats.value = await api.fetchPracticeStats() } catch (e) { console.warn('获取练习统计失败', e) }
  }
  const loadActiveSeason = async () => {
    try {
      const data = await api.fetchPublicProfile()
      activeSeason.value = data.settings?.active_season || ''
      availableSeasons.value = data.available_seasons || []
    } catch (e) { console.warn('加载招聘季失败', e) }
  }
  const loadAllData = () => { fetchTableData(); fetchAnalytics(); fetchPracticeStats(); loadActiveSeason() }

  // ── Re-fetch when tag filter changes (server-side filtering) ──
  watch(selectedTag, () => {
    fetchTableData()
  })

  // ── Computed: tags ──
  const popularTags = computed(() => {
    if (popularTagsFromServer.value.length > 0) {
      const result = {}
      for (const t of popularTagsFromServer.value) { result[t.tag] = t.count }
      return result
    }
    const counts = {}
    masterBank.value.forEach(q => {
      const cats = (q.cat1 || '未分类').split(',').map(c => c.trim()).filter(c => c)
      if (cats.length === 0) counts['未分类'] = (counts['未分类'] || 0) + 1
      else cats.forEach(cat => counts[cat] = (counts[cat] || 0) + 1)
    })
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).reduce((acc, [k, v]) => { acc[k] = v; return acc }, {})
  })
  const availableSubTags = computed(() => {
    if (selectedTag.value === '全部') return []
    const catItems = masterBank.value.filter(q =>
      (q.cat1 || '未分类').split(',').map(c => c.trim()).includes(selectedTag.value)
    )
    const counts = {}
    catItems.forEach(q => {
      const tags = (q.tags || '').split(',').map(t => t.trim()).filter(t => t)
      tags.forEach(tag => { counts[tag] = (counts[tag] || 0) + 1 })
    })
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([tag, count]) => ({ tag, count }))
  })

  // ── Computed: filtered data ──
  const filteredMasterBank = computed(() => {
    let result = masterBank.value
    if (selectedTag.value !== '全部') {
      result = result.filter(q => (q.cat1 || '未分类').split(',').map(c => c.trim()).includes(selectedTag.value))
    }
    if (selectedSubTags.value.length > 0) {
      result = result.filter(q => {
        const itemTags = (q.tags || '').split(',').map(t => t.trim()).filter(t => t)
        return selectedSubTags.value.some(st => itemTags.includes(st))
      })
    }
    if (searchQuery.value.trim()) {
      const query = searchQuery.value.trim().toLowerCase()
      result = result.filter(q => {
        if ((q.question || '').toLowerCase().includes(query)) return true
        if ((q.cat1 || '').toLowerCase().includes(query)) return true
        if ((q.tags || '').toLowerCase().includes(query)) return true
        if (q.original_questions && Array.isArray(q.original_questions)) {
          return q.original_questions.some(oq => {
            const text = typeof oq === 'string' ? oq : (oq.question || '')
            return text.toLowerCase().includes(query)
          })
        }
        return false
      })
    }
    if (filterDifficulty.value) result = result.filter(q => (q.difficulty || '').includes(filterDifficulty.value))
    if (showStarredOnly.value) result = result.filter(q => q.is_starred)
    return result
  })
  const interviewSeasons = computed(() => {
    const seasons = [...new Set(interviewData.value.map(d => d.season).filter(Boolean))]
    return seasons.sort()
  })
  const filteredInterviewData = computed(() => {
    let data = filterSeason.value
      ? interviewData.value.filter(d => d.season === filterSeason.value)
      : [...interviewData.value]
    data.sort((a, b) => {
      const da = a.created_at || ''
      const db = b.created_at || ''
      return interviewSortOrder.value === 'desc' ? db.localeCompare(da) : da.localeCompare(db)
    })
    return data
  })
  const practicedQuestions = computed(() => {
    const stats = practiceStats.value
    if (!stats?.practiced_details) return {}
    return stats.practiced_details
  })

  const formatDate = (dateStr) => {
    if (!dateStr) return '-'
    return dateStr.replace('T', ' ').slice(0, 16)
  }

  return {
    // data
    jdData, interviewData, masterBank,
    isDataLoading, dataLoadError,
    analytics, practiceStats, popularTags,
    activeSeason, availableSeasons,
    // infinite scroll
    isLoadingMore, hasMore, loadMoreMasterBank,
    // filters
    selectedTag, selectedSubTags, searchQuery,
    filterDifficulty, showStarredOnly,
    filterSeason, interviewSortOrder,
    // computed
    filteredMasterBank, filteredInterviewData,
    availableSubTags, interviewSeasons, practicedQuestions,
    // functions
    fetchTableData, fetchAnalytics, fetchPracticeStats,
    loadActiveSeason, loadAllData,
    // utils
    formatDate,
  }
}

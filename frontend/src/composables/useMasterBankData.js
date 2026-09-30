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
import { useToast } from './useNotification.js'

export function useMasterBankData({ onAfterFetch } = {}) {
  const toast = useToast()
  // ── Core data ──
  const jdData = ref([])
  const interviewData = ref([])
  const masterBank = ref([])
  const isDataLoading = ref(false)
  const dataLoadError = ref(null)
  const analytics = ref({ tech_trends: {} })
  const popularTagsFromServer = ref([])
  const categoryCountsFromServer = ref([])
  const filteredTagCountsFromServer = ref([])
  const masterBankTotal = ref(0)
  const masterBankOverallTotal = ref(0)
  const interviewTotal = ref(0)
  const practiceStats = ref({})
  const activeSeason = ref('')
  const availableSeasons = ref([])

  // ── Infinite scroll pagination ──
  const PAGE_SIZE = 30
  const currentPage = ref(1)
  const hasMore = ref(true)
  const isLoadingMore = ref(false)
  const requestVersion = ref(0)

  // ── Filters ──
  const bankFilter = ref('all')  // all/public/mine（题库过滤口径）
  const selectedTag = ref('全部')
  const selectedSubTags = ref([])
  const searchQuery = ref('')
  const filterDifficulty = ref('')
  const showStarredOnly = ref(false)
  const filterSeason = ref('')
  const interviewSortOrder = ref('desc')
  // R09：面经列表按岗位筛选时传给服务端的 position_id（与 location 同协议）
  const interviewPositionId = ref('')

  const decorateQuestion = (q) => ({
    ...q, _showAnswer: false, _showSources: false, _showAnswerSources: false,
    _isLoadingAnswer: false, _isRetagging: false, _isEditingAnswer: false, _editAnswer: ''
  })

  const applyMasterBankMeta = (resp) => {
    const total = Number(resp.total || 0)
    masterBankTotal.value = total
    if (resp.overall_total !== undefined) masterBankOverallTotal.value = Number(resp.overall_total || total)
    if (resp.popular_tags) popularTagsFromServer.value = resp.popular_tags
    if (resp.category_counts) categoryCountsFromServer.value = resp.category_counts
    if (resp.filtered_tag_counts) filteredTagCountsFromServer.value = resp.filtered_tag_counts
  }

  // ── Data fetching ──
  const fetchTableData = async ({ resetSubTags = true } = {}) => {
    const currentRequestVersion = ++requestVersion.value
    if (resetSubTags) selectedSubTags.value = []
    const requestTag = selectedSubTags.value.join(',')
    isDataLoading.value = true
    dataLoadError.value = null
    invalidateCache()
    currentPage.value = 1
    hasMore.value = true
    filteredTagCountsFromServer.value = []
    try {
      const [jdResp, intResp, masterResp] = await Promise.all([
        api.fetchJdData(), fetchAllInterviewPages(), api.fetchMasterBank({ page: 1, page_size: PAGE_SIZE, cat1: selectedTag.value !== '全部' ? selectedTag.value : undefined, tag: requestTag || undefined, filter: bankFilter.value })
      ])
      if (currentRequestVersion !== requestVersion.value) return
      jdData.value = (jdResp.items || jdResp).map(item => ({ ...item }))
      interviewData.value = (intResp.items || intResp).map(item => ({ ...item }))
      interviewTotal.value = intResp.total ?? interviewData.value.length
      const items = (masterResp.items || masterResp).map(decorateQuestion)
      masterBank.value = items
      // 检查是否还有更多数据
      applyMasterBankMeta(masterResp)
      hasMore.value = items.length < masterBankTotal.value
      currentPage.value = 1
      onAfterFetch?.()
    } catch (e) {
      if (currentRequestVersion !== requestVersion.value) return
      dataLoadError.value = getFriendlyError(e, '数据加载失败，请刷新重试')
    } finally {
      if (currentRequestVersion === requestVersion.value) isDataLoading.value = false
    }
  }

  /**
   * 拉取全部面经历页（R09/AC-002）：以服务端 total 为准循环取页，
   * 不再只取第一页 100 条本地切片；筛选/排序与 location 接口同协议。
   */
  const fetchAllInterviewPages = async () => {
    const pageSize = 100
    const first = await api.fetchInterviewData({
      page: 1,
      page_size: pageSize,
      season: filterSeason.value || undefined,
      position_id: interviewPositionId.value || undefined,
      sort: interviewSortOrder.value === 'asc' ? 'created_asc' : 'created_desc',
      scope: 'all',
    })
    const items = [...(first.items || first)]
    const total = first.total ?? items.length
    const pages = Math.ceil(total / pageSize)
    const rest = []
    for (let page = 2; page <= pages; page += 1) {
      try {
        const resp = await api.fetchInterviewData({
          page,
          page_size: pageSize,
          season: filterSeason.value || undefined,
          position_id: interviewPositionId.value || undefined,
          sort: interviewSortOrder.value === 'asc' ? 'created_asc' : 'created_desc',
          scope: 'all',
        })
        rest.push(...(resp.items || resp))
      } catch { break }
    }
    return { items: [...items, ...rest], total }
  }

  /** 加载下一页题库数据（无限滚动） */
  const loadMoreMasterBank = async () => {
    if (isDataLoading.value || isLoadingMore.value || !hasMore.value) return
    const currentRequestVersion = requestVersion.value
    const requestTag = selectedSubTags.value.join(',')
    isLoadingMore.value = true
    try {
      const nextPage = currentPage.value + 1
      const resp = await api.fetchMasterBank({
        page: nextPage,
        page_size: PAGE_SIZE,
        cat1: selectedTag.value !== '全部' ? selectedTag.value : undefined,
        tag: requestTag || undefined,
        filter: bankFilter.value,
      })
      if (currentRequestVersion !== requestVersion.value) return
      const newItems = (resp.items || resp).map(decorateQuestion)
      if (newItems.length > 0) {
        masterBank.value = [...masterBank.value, ...newItems]
        currentPage.value = nextPage
      }
      applyMasterBankMeta(resp)
      hasMore.value = masterBank.value.length < masterBankTotal.value
    } catch (e) {
      console.warn('加载更多题目失败', e)
      toast.warning('加载更多题目失败，请重试')
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
  const categoryCounts = computed(() => {
    if (categoryCountsFromServer.value.length > 0) {
      const result = {}
      for (const item of categoryCountsFromServer.value) result[item.category] = item.count
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
    if (filteredTagCountsFromServer.value.length > 0) {
      return filteredTagCountsFromServer.value.map(({ tag, count }) => ({ tag, count }))
    }
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
    jdData, interviewData, masterBank, bankFilter,
    isDataLoading, dataLoadError,
    analytics, practiceStats, popularTags, categoryCounts,
    masterBankTotal, masterBankOverallTotal, interviewTotal,
    activeSeason, availableSeasons,
    // infinite scroll
    isLoadingMore, hasMore, loadMoreMasterBank,
    // filters
    selectedTag, selectedSubTags, searchQuery,
    filterDifficulty, showStarredOnly,
    filterSeason, interviewSortOrder,
    interviewPositionId,
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

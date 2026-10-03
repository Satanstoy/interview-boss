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
  const interviewCurrentPage = ref(1)
  const interviewPageSize = ref(20)
  const practiceStats = ref({})
  const activeSeason = ref('')
  const availableSeasons = ref([])

  // ── Infinite scroll pagination ──
  const PAGE_SIZE = 30
  const currentPage = ref(1)
  const hasMore = ref(true)
  const isLoadingMore = ref(false)
  const requestVersion = ref(0)
  const interviewPageRequestVersion = ref(0)

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
      const [jdResp, , masterResp] = await Promise.all([
        api.fetchJdData(), loadInterviewPage(interviewCurrentPage.value, interviewPageSize.value), api.fetchMasterBank({ page: 1, page_size: PAGE_SIZE, cat1: selectedTag.value !== '全部' ? selectedTag.value : undefined, tag: requestTag || undefined, filter: bankFilter.value })
      ])
      if (currentRequestVersion !== requestVersion.value) return
      // 招聘季全集独立拉取（server 模式下面经数据仅当前页，season 选项需全集）
      fetchInterviewSeasonSource()
          .then(source => { interviewSeasonSource.value = source })
          .catch(() => {})
      jdData.value = (jdResp.items || jdResp).map(item => ({ ...item }))
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
   * 拉取面经单页（AC-002/contracts §4.5）：分页由服务端驱动，
   * total 以服务端为准；返回 {items, total}。
   */
  const fetchInterviewPage = async (page = 1, pageSize = 20) => {
    const resp = await api.fetchInterviewData({
      page,
      page_size: pageSize,
      season: filterSeason.value || undefined,
      position_id: interviewPositionId.value || undefined,
      sort: interviewSortOrder.value === 'asc' ? 'created_at_asc' : 'created_at_desc',
      scope: 'all',
    })
    return { items: resp.items || resp, total: resp.total ?? (resp.items || resp).length }
  }

  /** 面经当前页数据（server 模式：页码变化时由调用方 fetchInterviewPage 更新） */
  const interviewPageData = ref([])
  /** 招聘季全集（独立于分页数据，避免换页丢失 season 选项） */
  const interviewSeasonSource = ref([])

  /** 招聘季全集来源：一次全量拉取（不用于展示，仅推断 season 选项） */
  const fetchInterviewSeasonSource = async () => {
    const resp = await api.fetchInterviewData({
      page: 1,
      page_size: 500,
      season: filterSeason.value || undefined,
      position_id: interviewPositionId.value || undefined,
      sort: 'created_at_desc',
      scope: 'all',
    })
    return resp.items || resp
  }

  /** 面经列表换页：向服务端拉取目标页并刷新当前页数据（合约 §4.5 server 模式） */
  const loadInterviewPage = async (page = 1, pageSize = 20) => {
    const currentRequestVersion = ++interviewPageRequestVersion.value
    const { items, total } = await fetchInterviewPage(page, pageSize)
    if (currentRequestVersion === interviewPageRequestVersion.value) {
      interviewPageData.value = items.map(item => ({ ...item }))
      interviewData.value = interviewPageData.value
      interviewTotal.value = total
    }
    return { items, total }
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

  // contracts §4.5 server 模式：招聘季/排序变化时回第 1 页重新按页拉取
  watch([filterSeason, interviewSortOrder], () => {
    interviewCurrentPage.value = 1
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
    const seasons = [...new Set(interviewSeasonSource.value.map(d => d.season).filter(Boolean))]
    return seasons.sort()
  })
  const filteredInterviewData = computed(() => {
    // server 模式（contracts §4.5）：面经数据由服务端按 page/season/sort/
    // position 过滤，前端直接展示当前页，不再本地二次过滤或 slice。
    return interviewData.value
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
    interviewCurrentPage, interviewPageSize,
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
    loadInterviewPage, fetchInterviewPage,
    // utils
    formatDate,
  }
}

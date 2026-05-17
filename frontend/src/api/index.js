import { get, post, put, del, upload, uploadSSE, postSSE, fetchWithCredentials, invalidateCache } from '../utils/http.js'

const API = '/api'

// ── Auth ──
export const authRegister = (username, password) => post(`${API}/auth/register`, { username, password })
export const authLogin = (username, password, remember_me = false) => post(`${API}/auth/login`, { username, password, remember_me })
export const authMe = () => get(`${API}/auth/me`)
export const authUpdateBankMode = (bank_mode) => put(`${API}/auth/bank-mode`, { bank_mode })
export const authRefresh = () => post(`${API}/auth/refresh`, null)
export const authLogout = async () => {
  try {
    await fetchWithCredentials(`${API}/auth/logout`, { method: 'POST' })
  } catch { /* 忽略网络错误，前端仍会清除本地状态 */ }
}

// ── Email Auth ──
export const sendVerifyCode = (email, purpose) => post(`${API}/auth/send-code`, { email, purpose })
export const authRegisterWithEmail = (email, code, username, password) => post(`${API}/auth/register-with-email`, { email, code, username, password })
export const authLoginWithEmail = (email, code) => post(`${API}/auth/login-with-email`, { email, code })

// ── Email Binding ──
export const getMyEmail = () => get(`${API}/profile/email`)
export const sendBindCode = (email) => post(`${API}/profile/send-bind-code`, { email })
export const bindEmail = (email, code) => post(`${API}/profile/bind-email`, { email, code })

// ── Data fetching ──
export const fetchJdData = (page = 1, pageSize = 100) => get(`${API}/data/jd?page=${page}&page_size=${pageSize}`)
export const fetchInterviewData = (page = 1, pageSize = 100) => get(`${API}/data/interview?page=${page}&page_size=${pageSize}`)
export const fetchMasterBank = (params = {}) => {
  const query = new URLSearchParams({
    page: params.page || 1,
    page_size: params.page_size || 500,
    sort: params.sort || 'frequency_desc',
    ...params,
    compact: 'true',  // Always use compact mode to reduce bandwidth
  })
  return get(`${API}/master-bank?${query}`)
}
export const fetchAnalytics = () => get(`${API}/analytics`)
export const fetchPracticeStats = () => get(`${API}/practice-stats`)
export const fetchRandomQuestions = ({ count = 10, cat1, difficulty } = {}) => {
  const params = new URLSearchParams({ count: String(count) })
  if (cat1) params.append('cat1', cat1)
  if (difficulty) params.append('difficulty', difficulty)
  return get(`${API}/master-bank/random?${params}`)
}

// ── Submit ──
export const submitData = (formData) => upload(`${API}/submit`, formData)
export const submitDataSSE = (formData, onEvent) => uploadSSE(`${API}/submit-stream`, formData, onEvent)

// ── Data mutations ──
export const deleteRecord = (type, id) => del(`${API}/data/${type}/${id}`)
export const updateRecord = (data) => put(`${API}/data/update`, data)
export const restoreRecord = (type, id) => post(`${API}/data/restore/${type}/${id}`)
export const fetchTrash = (type, page = 1, pageSize = 100) => get(`${API}/data/${type}/trash?page=${page}&page_size=${pageSize}`)

// ── Interview ──
export const reprocessInterview = (id) => post(`${API}/interview/${id}/re-process`)
export const reprocessInterviewSSE = (id, onEvent) => postSSE(`${API}/interview/${id}/re-process-stream`, null, onEvent)

// ── Master bank ──
export const buildMasterBank = () => post(`${API}/master-bank/build`, null, { timeout: 600_000, noRetry: true })
export const buildMasterBankSSE = (onEvent) => postSSE(`${API}/master-bank/build`, null, onEvent)
export const buildPersonalBankSSE = (onEvent) => postSSE(`${API}/master-bank/build-personal`, null, onEvent)
export const retagQuestion = (id) => post(`${API}/master-bank/re-tag/${id}`, null, { timeout: 180_000 })
export const generateAnswer = (id) => post(`${API}/master-bank/generate-answer/${id}`, null, { timeout: 180_000 })
export const useReferenceAnswer = (id) => post(`${API}/master-bank/use-reference-answer/${id}`, null, { timeout: 30_000 })
export const saveUserAnswer = (id, answer) => put(`${API}/master-bank/save-user-answer/${id}`, { answer })
export const evaluateAnswer = (data) => post(`${API}/evaluate-answer`, data, { timeout: 180_000 })
export const toggleStar = (id) => post(`${API}/master-bank/toggle-star/${id}`)
export const deleteMasterQuestion = (id) => del(`${API}/master-bank/${id}`)
export const updateQuestion = (id, data) => put(`${API}/master-bank/${id}`, data)
export const splitQuestion = (id, originalQuestion) => post(`${API}/master-bank/split-question/${id}`, { original_question: originalQuestion })
export const deleteOriginalQuestion = (id, originalQuestion) => post(`${API}/master-bank/delete-original-question/${id}`, { original_question: originalQuestion })
export const mergeQuestion = (id, originalQuestion, targetId, targetCat1 = '', targetCat2 = '') => post(`${API}/master-bank/merge-question/${id}`, { original_question: originalQuestion, target_id: targetId, target_cat1: targetCat1, target_cat2: targetCat2 })
export const searchMasterBank = (q, excludeId) => {
  const params = new URLSearchParams({ q: q || '', limit: '20' })
  if (excludeId) params.append('exclude_id', String(excludeId))
  return get(`${API}/master-bank/search?${params}`)
}
export const getAnalysisStatus = () => get(`${API}/master-bank/analysis-status`)

// ── Bank upload & review ──
export const uploadToBank = ({ question_text, cat1, cat2, tags, difficulty, target }) =>
  post(`${API}/master-bank/upload`, { question_text, cat1: cat1 || '', cat2: cat2 || '', tags: tags || '', difficulty: difficulty || '', target: target || 'public' })
export const fetchPendingQuestions = () => get(`${API}/master-bank/pending`)
export const approveQuestion = (id) => post(`${API}/master-bank/approve/${id}`)
export const rejectQuestion = (id) => post(`${API}/master-bank/reject/${id}`)

// ── Batch operations ──
export const batchDeleteData = (fileType, ids) => post(`${API}/data/batch-delete`, { file_type: fileType, ids })
export const batchDeleteMasterBank = (ids) => post(`${API}/master-bank/batch-delete`, { ids })
export const batchGenerateAnswers = (ids, onEvent) => postSSE(`${API}/master-bank/batch-generate-answers`, { ids }, onEvent)

// ── Trash & Restore ──
export const fetchMasterBankTrash = (page = 1, pageSize = 50) => get(`${API}/master-bank/trash?page=${page}&page_size=${pageSize}`)
export const restoreQuestion = (id) => post(`${API}/master-bank/restore/${id}`)
export const batchRestoreMasterBank = (ids) => post(`${API}/master-bank/batch-restore`, { ids })

// ── Knowledge Graph ──
export const fetchKnowledgeGraph = () => get(`${API}/knowledge-graph`)

// ── Profile ──
export const fetchProfile = () => get(`${API}/profile`)
export const fetchPublicProfile = () => get(`${API}/profile/public`)
export const updateProfile = (settings) => put(`${API}/profile`, { settings })
export const switchPosition = (position) => put(`${API}/profile/position`, { position })
export const switchPositionById = (position_id) => put(`${API}/profile/position`, { position_id })
export const switchMyPosition = (position) => put(`${API}/profile/my-position`, { position })
export const fetchPositions = () => get(`${API}/positions`)
export const deletePosition = (position) => del(`${API}/profile/position/${encodeURIComponent(position)}`)
export const createPosition = (name, description = '') => post(`${API}/positions`, { name, description })

// ── Taxonomy AI Suggestion ──
export const generateTaxonomy = () => post(`${API}/profile/taxonomy/generate`, null, { timeout: 180_000 })
export const confirmTaxonomy = (categories) => post(`${API}/profile/taxonomy/confirm`, { categories })
export const savePersonalTaxonomy = (categories) => post(`${API}/profile/taxonomy/save-personal`, { categories })
export const shareTaxonomy = (taxonomyId) => post(`${API}/profile/taxonomy/${taxonomyId}/share`)
export const fetchPublicTaxonomies = () => get(`${API}/profile/taxonomy/public`)
export const deletePublicTaxonomy = (taxonomyId) => del(`${API}/profile/taxonomy/${taxonomyId}/public`)

// ── Per-user LLM Config ──
export const fetchMyLLMConfig = () => get(`${API}/profile/llm`)
export const updateMyLLMConfig = (settings) => put(`${API}/profile/llm`, settings)
export const deleteMyLLMConfig = () => del(`${API}/profile/llm`)

// ── Practice History ──
export const fetchPracticeHistory = (questionId) => get(`${API}/practice-history/${questionId}`)

// ── Cache Management ──
export { invalidateCache }

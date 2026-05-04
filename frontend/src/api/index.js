import { get, post, put, del, upload, postSSE } from '../utils/http.js'

const API = '/api'

// ── Data fetching ──
export const fetchJdData = () => get(`${API}/data/jd?page_size=500`)
export const fetchInterviewData = () => get(`${API}/data/interview?page_size=500`)
export const fetchMasterBank = () => get(`${API}/master-bank?page_size=500`)
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

// ── Data mutations ──
export const deleteRecord = (type, id) => del(`${API}/data/${type}/${id}`)
export const updateRecord = (data) => put(`${API}/data/update`, data)

// ── Interview ──
export const reprocessInterview = (id) => post(`${API}/interview/${id}/re-process`)

// ── Master bank ──
export const buildMasterBank = () => post(`${API}/master-bank/build`)
export const retagQuestion = (id) => post(`${API}/master-bank/re-tag/${id}`)
export const generateAnswer = (id) => post(`${API}/master-bank/generate-answer/${id}`)
export const evaluateAnswer = (data) => post(`${API}/evaluate-answer`, data)
export const toggleStar = (id) => post(`${API}/master-bank/toggle-star/${id}`)
export const deleteMasterQuestion = (id) => del(`${API}/master-bank/${id}`)

// ── Batch operations ──
export const batchDeleteData = (fileType, ids) => post(`${API}/data/batch-delete`, { file_type: fileType, ids })
export const batchDeleteMasterBank = (ids) => post(`${API}/master-bank/batch-delete`, { ids })
export const batchGenerateAnswers = (ids, onEvent) => postSSE(`${API}/master-bank/batch-generate-answers`, { ids }, onEvent)

// ── Download ──
export const getDownloadUrl = (type) => `${API}/download/${type}`

// ── Knowledge Graph ──
export const fetchKnowledgeGraph = () => get(`${API}/knowledge-graph`)

// ── Profile ──
export const fetchProfile = () => get(`${API}/profile`)
export const updateProfile = (settings) => put(`${API}/profile`, { settings })

// ── Practice History ──
export const fetchPracticeHistory = (questionId) => get(`${API}/practice-history/${questionId}`)

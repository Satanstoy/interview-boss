import { get, post, put, del, postSSE, getSSE } from './http.js'

const API = '/api'

// ── Master bank ──
export const buildMasterBank = () => post(`${API}/master-bank/build`, null, { timeout: 600_000, noRetry: true })
export const buildMasterBankSSE = (onEvent) => postSSE(`${API}/master-bank/build`, null, onEvent)
export const streamJobProgress = (jobId, onEvent) => getSSE(`${API}/jobs/${jobId}/stream`, onEvent)
export const buildPersonalBankSSE = (onEvent) => postSSE(`${API}/master-bank/build-personal`, null, onEvent)
export const retagQuestion = (id) => post(`${API}/master-bank/re-tag/${id}`, null, { timeout: 180_000 })
export const generateAnswer = (id) => post(`${API}/master-bank/generate-answer/${id}`, null, { timeout: 180_000 })
export const useReferenceAnswer = (id) => post(`${API}/master-bank/use-reference-answer/${id}`, null, { timeout: 30_000 })
export const saveUserAnswer = (id, answer) => put(`${API}/master-bank/save-user-answer/${id}`, { answer })
export const generateRecitation = (id) => post(`${API}/master-bank/generate-recitation/${id}`, null, { timeout: 180_000 })
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
export const batchDeleteMasterBank = (ids) => post(`${API}/master-bank/batch-delete`, { ids })
export const batchGenerateAnswers = (ids, onEvent) => postSSE(`${API}/master-bank/batch-generate-answers`, { ids }, onEvent)

// ── Trash & Restore ──
export const fetchMasterBankTrash = (page = 1, pageSize = 50) => get(`${API}/master-bank/trash?page=${page}&page_size=${pageSize}`)
export const restoreQuestion = (id) => post(`${API}/master-bank/restore/${id}`)
export const batchRestoreMasterBank = (ids) => post(`${API}/master-bank/batch-restore`, { ids })


export const shareQuestionToBank = (questionId) => post(`${API}/master-bank/${questionId}/share`)

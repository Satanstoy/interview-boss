import { get, post, put, del, upload, uploadSSE } from './http.js'

const API = '/api'

// ── Data fetching ──
export const fetchJdData = (page = 1, pageSize = 100) => get(`${API}/data/jd?page=${page}&page_size=${pageSize}`)
export const fetchInterviewData = (page = 1, pageSize = 100) => get(`${API}/data/interview?page=${page}&page_size=${pageSize}`)
export const fetchMasterBank = (params = {}) => {
  // Filter out undefined values to prevent URLSearchParams from converting them to "undefined" string
  const cleanParams = Object.fromEntries(
    Object.entries(params).filter(([_, v]) => v !== undefined)
  )
  const query = new URLSearchParams({
    page: params.page || 1,
    page_size: params.page_size || 500,
    sort: params.sort || 'frequency_desc',
    ...cleanParams,
    compact: 'true',  // Always use compact mode to reduce bandwidth
  })
  return get(`${API}/master-bank?${query}`)
}

// ── Submit ──
export const submitData = (formData) => upload(`${API}/submit`, formData)
export const submitDataSSE = (formData, onEvent) => uploadSSE(`${API}/submit-stream-v2`, formData, onEvent)

// ── Submit jobs (后台任务模式) ──
export const createSubmitJob = (formData) => upload(`${API}/submit-jobs`, formData, { timeout: 120_000, noRetry: true })
export const fetchActiveSubmitJobs = () => get(`${API}/submit-jobs/active`, { noCache: true })
export const retrySubmitJob = (jobId) => post(`${API}/submit-jobs/${jobId}/retry`, {})

// ── Data mutations ──
export const deleteRecord = (type, id, options = {}) => del(`${API}/data/${type}/${id}`, options)
export const updateRecord = (data) => put(`${API}/data/update`, data)
export const restoreRecord = (type, id) => post(`${API}/data/restore/${type}/${id}`)
export const fetchTrash = (type, page = 1, pageSize = 100) => get(`${API}/data/${type}/trash?page=${page}&page_size=${pageSize}`)

// ── Batch operations (data) ──
export const batchDeleteData = (fileType, ids) => post(`${API}/data/batch-delete`, { file_type: fileType, ids })

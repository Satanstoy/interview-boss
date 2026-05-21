import { get, post, put, del, upload, uploadSSE } from './http.js'

const API = '/api'

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

// ── Submit ──
export const submitData = (formData) => upload(`${API}/submit`, formData)
export const submitDataSSE = (formData, onEvent) => uploadSSE(`${API}/submit-stream-v2`, formData, onEvent)

// ── Data mutations ──
export const deleteRecord = (type, id) => del(`${API}/data/${type}/${id}`)
export const updateRecord = (data) => put(`${API}/data/update`, data)
export const restoreRecord = (type, id) => post(`${API}/data/restore/${type}/${id}`)
export const fetchTrash = (type, page = 1, pageSize = 100) => get(`${API}/data/${type}/trash?page=${page}&page_size=${pageSize}`)

// ── Batch operations (data) ──
export const batchDeleteData = (fileType, ids) => post(`${API}/data/batch-delete`, { file_type: fileType, ids })

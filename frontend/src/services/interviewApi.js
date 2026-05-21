import { post, postSSE } from './http.js'

const API = '/api'

// ── Interview ──
export const reprocessInterview = (id) => post(`${API}/interview/${id}/re-process`)
export const reprocessInterviewSSE = (id, onEvent) => postSSE(`${API}/interview/${id}/re-process-stream`, null, onEvent)

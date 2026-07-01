import { get, post, postSSE } from './http.js'

const API = '/api'

// ── Interview ──
export const getExperiences = () => get(`${API}/interview/experiences`, { noCache: true })
export const reprocessInterview = (id) => post(`${API}/interview/${id}/re-process`)
export const reprocessInterviewSSE = (id, onEvent) => postSSE(`${API}/interview/${id}/re-process-stream`, null, onEvent)

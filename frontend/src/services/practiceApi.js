import { get, post } from './http.js'

const API = '/api'

// ── Practice History ──
export const fetchPracticeHistory = (questionId) => get(`${API}/practice-history/${questionId}`)

// ── Answer Evaluation ──
export const evaluateAnswer = (data) => post(`${API}/evaluate-answer`, data, { timeout: 180_000 })

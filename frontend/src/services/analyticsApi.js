import { get } from './http.js'

const API = '/api'

// ── Analytics ──
export const fetchAnalytics = () => get(`${API}/analytics`)
export const fetchPracticeStats = () => get(`${API}/practice-stats`)

// ── Knowledge Graph ──
export const fetchKnowledgeGraph = () => get(`${API}/knowledge-graph`)

// ── Random questions (mock interview) ──
export const fetchRandomQuestions = ({ count = 10, cat1, difficulty } = {}) => {
  const params = new URLSearchParams({ count: String(count) })
  if (cat1) params.append('cat1', cat1)
  if (difficulty) params.append('difficulty', difficulty)
  return get(`${API}/master-bank/random?${params}`)
}

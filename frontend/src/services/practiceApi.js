import { del, get, post, put } from './http.js'

const API = '/api'

// ── Practice History ──
export const fetchPracticeHistory = (questionId) => get(`${API}/practice-history/${questionId}`)

// ── Answer Evaluation ──
export const evaluateAnswer = (data) => post(`${API}/evaluate-answer`, data, { timeout: 180_000 })

// ── Study Plans & Spaced Review ──
export const fetchPracticeDecks = (params = {}) => get(`${API}/practice/decks`, params)
export const fetchPracticeDeckQuestions = (deckKey, params = {}) => get(`${API}/practice/decks/${encodeURIComponent(deckKey)}/questions`, params)
export const submitPracticeReview = (data) => post(`${API}/practice/review`, data)
export const createPracticeDeck = (data) => post(`${API}/practice/decks`, data)
export const updatePracticeDeck = (deckKey, data) => put(`${API}/practice/decks/${encodeURIComponent(deckKey)}`, data)
export const deletePracticeDeck = (deckKey) => del(`${API}/practice/decks/${encodeURIComponent(deckKey)}`)
export const addPracticeDeckItem = (deckKey, questionId) => post(`${API}/practice/decks/${encodeURIComponent(deckKey)}/items`, { question_id: questionId })
export const removePracticeDeckItem = (deckKey, questionId) => del(`${API}/practice/decks/${encodeURIComponent(deckKey)}/items/${questionId}`)

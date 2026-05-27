import { get, post } from './http.js'

const API = '/api/coding'

export const fetchCodingProblems = (params) => get(`${API}/problems`, { params })

export const fetchCodingProblem = (id) => get(`${API}/problems/${id}`)

export const submitCodingCode = (data) => post(`${API}/submit`, data, { timeout: 180_000 })

export const fetchCodingSubmissions = (params) => get(`${API}/submissions`, { params })

export const fetchCodingSubmission = (id) => get(`${API}/submissions/${id}`)

export const fetchCodingErrorStats = () => get(`${API}/error-stats`)

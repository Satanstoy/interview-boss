import { get, post } from './http.js'

const API = '/api/coding'

export const fetchCodingProblems = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.difficulty) qs.append('difficulty', params.difficulty)
  if (params.tag) qs.append('tag', params.tag)
  if (params.page) qs.append('page', String(params.page))
  if (params.page_size) qs.append('page_size', String(params.page_size))
  const query = qs.toString()
  return get(`${API}/problems${query ? '?' + query : ''}`)
}

export const fetchCodingProblem = (id) => get(`${API}/problems/${id}`)

export const submitCodingCode = (data) => post(`${API}/submit`, data, { timeout: 180_000 })

export const fetchCodingSubmissions = (params) => get(`${API}/submissions`, { params })

export const fetchCodingSubmission = (id) => get(`${API}/submissions/${id}`)

export const fetchCodingErrorStats = () => get(`${API}/error-stats`)

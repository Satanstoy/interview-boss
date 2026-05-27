import { get, postSSE } from './http.js'

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

export const submitCodingCode = (data, onEvent) =>
  postSSE(`${API}/submit`, data, onEvent)

export const fetchCodingSubmissions = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.problem_id) qs.append('problem_id', String(params.problem_id))
  if (params.page) qs.append('page', String(params.page))
  if (params.page_size) qs.append('page_size', String(params.page_size))
  const query = qs.toString()
  return get(`${API}/submissions${query ? '?' + query : ''}`)
}

export const fetchCodingSubmission = (id) => get(`${API}/submissions/${id}`)

export const fetchCodingErrorStats = () => get(`${API}/error-stats`)

import { del, get, post, postSSE } from './http.js'

const API = '/api/coding'

export const fetchCodingProblems = (params = {}) => {
  const qs = new URLSearchParams()
  if (params.difficulty) qs.append('difficulty', params.difficulty)
  if (params.tag) qs.append('tag', params.tag)
  if (params.search) qs.append('search', params.search)
  if (params.scope) qs.append('scope', params.scope)
  if (params.playlist_id) qs.append('playlist_id', String(params.playlist_id))
  if (params.page) qs.append('page', String(params.page))
  if (params.page_size) qs.append('page_size', String(params.page_size))
  const query = qs.toString()
  return get(`${API}/problems${query ? '?' + query : ''}`)
}

export const fetchCodingProblem = (id) => get(`${API}/problems/${id}`)

export const toggleCodingFavorite = (id) => post(`${API}/problems/${id}/favorite`, {})

export const fetchCodingPlaylists = () => get(`${API}/playlists`, { noCache: true })

export const createCodingPlaylist = (data) => post(`${API}/playlists`, data)

export const deleteCodingPlaylist = (playlistId) =>
  del(`${API}/playlists/${playlistId}`)

export const moveCodingPlaylist = (playlistId, direction) =>
  post(`${API}/playlists/${playlistId}/move`, { direction })

export const addCodingPlaylistItem = (playlistId, problemId) =>
  post(`${API}/playlists/${playlistId}/items`, { problem_id: problemId })

export const removeCodingPlaylistItem = (playlistId, problemId) =>
  del(`${API}/playlists/${playlistId}/items/${problemId}`)

export const importCodingProblems = (data) => post(`${API}/import`, data, { timeout: 120000, noRetry: true })

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

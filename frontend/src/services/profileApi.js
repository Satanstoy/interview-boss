import { get, put, post, del, invalidateCache } from './http.js'

const API = '/api'

// ── Profile ──
export const fetchProfile = (options) => get(`${API}/profile`, options)
export const fetchPublicProfile = (options) => get(`${API}/profile/public`, options)
export const updateProfile = (settings) => put(`${API}/profile`, { settings })
export const switchPosition = (position) => put(`${API}/profile/position`, { position })
export const switchPositionById = (position_id) => put(`${API}/profile/position`, { position_id })
export const switchMyPosition = (position) => put(`${API}/profile/my-position`, { position })
export const fetchPositions = () => get(`${API}/positions`, { noCache: true })
export const deletePosition = async (position) => {
  const result = await del(`${API}/profile/position/${encodeURIComponent(position)}`)
  invalidateCache(`${API}/positions`)
  return result
}
export const createPosition = async (name, description = '') => {
  const result = await post(`${API}/positions`, { name, description })
  invalidateCache(`${API}/positions`)
  return result
}

// ── Taxonomy AI Suggestion ──
export const generateTaxonomy = () => post(`${API}/profile/taxonomy/generate`, null, { timeout: 180_000 })
export const confirmTaxonomy = (categories) => post(`${API}/profile/taxonomy/confirm`, { categories })
export const savePersonalTaxonomy = (categories) => post(`${API}/profile/taxonomy/save-personal`, { categories })
export const shareTaxonomy = (taxonomyId) => post(`${API}/profile/taxonomy/${taxonomyId}/share`)
export const fetchPublicTaxonomies = () => get(`${API}/profile/taxonomy/public`)
export const deletePublicTaxonomy = (taxonomyId) => del(`${API}/profile/taxonomy/${taxonomyId}/public`)

// ── Per-user LLM Config ──
export const fetchMyLLMConfig = () => get(`${API}/profile/llm`)
export const updateMyLLMConfig = (settings) => put(`${API}/profile/llm`, settings)
export const deleteMyLLMConfig = () => del(`${API}/profile/llm`)
export const fetchAvailableModels = () => get(`${API}/profile/llm/models`)

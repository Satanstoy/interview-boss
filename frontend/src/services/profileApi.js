import { get, put, post, del } from './http.js'

const API = '/api'

// ── Profile ──
export const fetchProfile = () => get(`${API}/profile`)
export const fetchPublicProfile = () => get(`${API}/profile/public`)
export const updateProfile = (settings) => put(`${API}/profile`, { settings })
export const switchPosition = (position) => put(`${API}/profile/position`, { position })
export const switchPositionById = (position_id) => put(`${API}/profile/position`, { position_id })
export const switchMyPosition = (position) => put(`${API}/profile/my-position`, { position })
export const fetchPositions = () => get(`${API}/positions`)
export const deletePosition = (position) => del(`${API}/profile/position/${encodeURIComponent(position)}`)
export const createPosition = (name, description = '') => post(`${API}/positions`, { name, description })

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

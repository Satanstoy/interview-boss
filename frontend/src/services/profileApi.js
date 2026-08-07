import { get, put, post, del, invalidateCache } from './http.js'

const API = '/api'

// ── Profile ──
export const fetchProfile = (options) => get(`${API}/profile`, options)
export const fetchPublicProfile = (options) => get(`${API}/profile/public`, options)
export const updateProfile = (settings) => put(`${API}/profile`, { settings })
export const updateActiveSeason = (active_season) => put(`${API}/profile/active-season`, { active_season })
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
export const fetchLLMStatus = (opts = {}) =>
  get(`${API}/profile/llm/status${opts.probe ? '?probe=1' : ''}`, { noCache: true })

// ── Per-user web search config ──
export const fetchMySearchConfig = () => get(`${API}/profile/search`, { noCache: true })
export const updateMySearchConfig = (settings) => put(`${API}/profile/search`, settings)
export const deleteMySearchConfig = () => del(`${API}/profile/search`)
export const testMySearchConfig = (query) => post(`${API}/profile/search/test`, { query })

// ── Per-account MCP connection ──
export const fetchMyMCPConfig = () => get(`${API}/profile/mcp`, { noCache: true })
export const rotateMyMCPToken = () => post(`${API}/profile/mcp/token`, null)
export const revokeMyMCPToken = () => del(`${API}/profile/mcp/token`)

// ── Recruitment time preference ──
export const fetchRecruitmentPref = () => get(`${API}/profile/recruitment`, { noCache: true })
export const updateRecruitmentPref = (payload) => put(`${API}/profile/recruitment`, payload)

// ── Admin: Global embedding config ──
export const fetchGlobalEmbeddingConfig = () => get(`${API}/profile/embedding`, { noCache: true })
export const updateGlobalEmbeddingConfig = (settings) => put(`${API}/profile/embedding`, settings)
export const testGlobalEmbedding = (settings) => post(`${API}/profile/embedding/test`, settings)
export const testGlobalLLM = () => post(`${API}/profile/llm/test-global`, {})

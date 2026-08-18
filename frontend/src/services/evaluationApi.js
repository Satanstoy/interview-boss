import { get, getSSE, post } from './http.js'

const ROOT = '/api/admin/evals'

export const fetchEvaluationOverview = (options = {}) => get(`${ROOT}/overview`, { noCache: true, ...options })
export const fetchEvaluationCapabilities = () => get(`${ROOT}/capabilities`, { noCache: true })
export const fetchEvaluationReleases = (params = {}) => {
  const query = new URLSearchParams()
  if (params.releaseType) query.set('release_type', params.releaseType)
  if (params.status) query.set('status', params.status)
  const suffix = query.toString() ? `?${query}` : ''
  return get(`${ROOT}/releases${suffix}`, { noCache: true })
}
export const fetchEvaluationBenchmarks = () => get(`${ROOT}/benchmarks`, { noCache: true })
export const fetchEvaluationRuns = (status = '') => {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return get(`${ROOT}/runs${suffix}`, { noCache: true })
}
export const fetchEvaluationRun = (runId) => get(`${ROOT}/runs/${runId}`, { noCache: true })
export const fetchEvaluationItem = (runId, itemId) => get(`${ROOT}/runs/${runId}/items/${itemId}`, { noCache: true })
export const createEvaluationRun = (payload) => post(`${ROOT}/runs`, payload)
export const cancelEvaluationRun = (runId) => post(`${ROOT}/runs/${runId}/cancel`, {})
export const retryFailedEvaluationRun = (runId) => post(`${ROOT}/runs/${runId}/retry-failed`, {})
export const createEvaluationExperiment = (payload) => post(`${ROOT}/experiments`, payload)
export const fetchEvaluationExperiment = (experimentId) => get(`${ROOT}/experiments/${experimentId}`, { noCache: true })
export const cancelEvaluationExperiment = (experimentId) => post(`${ROOT}/experiments/${experimentId}/cancel`, {})
export const fetchHumanReviews = (comparisonGroup = '') => {
  const suffix = comparisonGroup ? `?comparison_group=${encodeURIComponent(comparisonGroup)}` : ''
  return get(`${ROOT}/reviews${suffix}`, { noCache: true })
}
export const createHumanReview = (payload) => post(`${ROOT}/reviews`, payload)

export const streamEvaluationRun = (runId, onEvent, options = {}) => (
  getSSE(`${ROOT}/runs/${runId}/events`, onEvent, options)
)

export const streamEvaluationExperiment = (experimentId, onEvent, options = {}) => (
  getSSE(`${ROOT}/experiments/${experimentId}/events`, onEvent, options)
)

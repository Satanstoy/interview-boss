import { get, getSSE, post } from './http.js'
import { normalizeEvaluationOverview, normalizeRunSummary, parseCaseEvidenceView } from './evaluationSchemas.js'

const ROOT = '/api/admin/evals'

export const fetchEvaluationOverview = (options = {}) => get(`${ROOT}/overview`, { noCache: true, ...options }).then(normalizeEvaluationOverview)
export const fetchEvaluationCapabilities = () => get(`${ROOT}/capabilities`, { noCache: true })
export const fetchEvaluationReleases = (params = {}) => {
  const query = new URLSearchParams()
  if (params.releaseType) query.set('release_type', params.releaseType)
  if (params.status) query.set('status', params.status)
  const suffix = query.toString() ? `?${query}` : ''
  return get(`${ROOT}/releases${suffix}`, { noCache: true })
}
export const fetchProjectHarnessReleases = () => get(`${ROOT}/harness-releases`, { noCache: true })

export const fetchEvaluationBenchmarks = () => get(`${ROOT}/benchmarks`, { noCache: true })

export const fetchEvaluationRuns = (status = '') => {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return get(`${ROOT}/runs${suffix}`, { noCache: true }).then(data => ({
    ...data,
    runs: (data.runs || []).map(normalizeRunSummary),
  }))
}
export const fetchActiveEvaluations = () => get(`${ROOT}/active`, { noCache: true })
export const fetchEvaluationRun = (runId) => get(`${ROOT}/runs/${runId}`, { noCache: true }).then(normalizeRunSummary)
export const fetchEvaluationItem = (runId, itemId) => get(`${ROOT}/runs/${runId}/items/${itemId}`, { noCache: true })
export const fetchEvaluationEvidence = (runId, itemId) => (
  get(`${ROOT}/runs/${runId}/items/${itemId}/evidence`, { noCache: true }).then(parseCaseEvidenceView)
)
export const createEvaluationRun = (payload) => post(`${ROOT}/runs`, payload)
export const cancelEvaluationRun = (runId) => post(`${ROOT}/runs/${runId}/cancel`, {})
export const retryFailedEvaluationRun = (runId) => post(`${ROOT}/runs/${runId}/retry-failed`, {})
export const restartEvaluationRun = (runId) => post(`${ROOT}/runs/${runId}/restart`, {})
export const resumeEvaluationRun = (runId) => post(`${ROOT}/runs/${runId}/resume`, {})
export const createEvaluationExperiment = (payload) => post(`${ROOT}/experiments`, payload)
export const fetchEvaluationExperiment = (experimentId) => get(`${ROOT}/experiments/${experimentId}`, { noCache: true })
export const cancelEvaluationExperiment = (experimentId) => post(`${ROOT}/experiments/${experimentId}/cancel`, {})
export const fetchHumanReviews = (comparisonGroup = '') => {
  const suffix = comparisonGroup ? `?comparison_group=${encodeURIComponent(comparisonGroup)}` : ''
  return get(`${ROOT}/reviews${suffix}`, { noCache: true })
}

export const fetchEvaluationExperiments = (params = {}) => {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  const suffix = query.toString() ? `?${query}` : ''
  return get(`${ROOT}/experiments${suffix}`, { noCache: true })
}
export const createHumanReview = (payload) => post(`${ROOT}/reviews`, payload)

export const streamEvaluationRun = (runId, onEvent, options = {}) => (
  getSSE(`${ROOT}/runs/${runId}/events`, onEvent, options)
)

export const streamEvaluationExperiment = (experimentId, onEvent, options = {}) => (
  getSSE(`${ROOT}/experiments/${experimentId}/events`, onEvent, options)
)

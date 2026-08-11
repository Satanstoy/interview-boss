// 聚合质量审查清单 API（管理员）
import http from './http.js'

export async function startQualityScan(options = {}) {
  const params = new URLSearchParams()
  Object.entries(options).forEach(([key, value]) => {
    if (value !== undefined && value !== null) params.set(key, String(value))
  })
  const query = params.toString()
  return http.post(`/api/admin/quality-issues/generate-all${query ? `?${query}` : ''}`)
}

export async function fetchQualityScanJob(jobId) {
  return http.get(`/api/jobs/${jobId}`, { ttl: 0 })
}

export async function fetchQualityIssues(status = 'pending') {
  return http.get(`/api/admin/quality-issues?status=${status}`)
}

export async function approveQualityIssue(issueId) {
  return http.post(`/api/admin/quality-issues/${issueId}/approve`)
}

export async function rejectQualityIssue(issueId) {
  return http.post(`/api/admin/quality-issues/${issueId}/reject`)
}

export async function batchApproveQualityIssues(issueIds, minConfidence = 0.85) {
  return http.post('/api/admin/quality-issues/batch-approve', {
    issue_ids: issueIds,
    min_confidence: minConfidence,
  })
}

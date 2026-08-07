// 聚合质量审查清单 API（管理员）
import http from './http.js'

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

// 来源健康 API（管理员）：同签名重复公共面经的列表与合并
import http from './http.js'

export async function fetchDuplicateGroups(table = 'interview') {
  // ttl:0 绕过 http.js 30s GET 缓存，避免合并后刷新读到旧数据
  return http.get(`/api/admin/source-health/duplicate-groups?table=${table}`, { ttl: 0 })
}

export function mergeDuplicateGroup(signature, table = 'interview', dryRun = false) {
  return http.post('/api/admin/source-health/duplicate-groups/merge', {
    signature,
    table,
    dry_run: dryRun,
  })
}

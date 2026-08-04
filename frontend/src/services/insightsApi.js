import { get } from './http.js'

/** 获取当前用户当前岗位的洞察快照。 */
export function fetchInsights(options = {}) {
  return get('/api/insights', options)
}

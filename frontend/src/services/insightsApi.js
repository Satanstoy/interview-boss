import { get } from './http.js'

/** 获取当前用户当前岗位的洞察快照。 */
export function fetchInsights(options = {}) {
  return get('/api/insights', options)
}

/** 获取用户练习足迹图表数据（热力图/连击/趋势/雷达/难度/最近刷题）。 */
export function fetchPracticeActivity(options = {}) {
  return get('/api/insights/practice-activity', options)
}

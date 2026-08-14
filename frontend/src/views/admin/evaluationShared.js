export const STATUS_LABELS = {
  created: '待调度',
  queued: '排队中',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

export const RELEASE_TYPE_LABELS = {
  target: 'Agent / Workflow',
  benchmark_suite: 'Benchmark Suite',
  eval_protocol: 'Eval Protocol',
  judge: 'Judge',
  simulator_harness: 'Simulator Harness',
  candidate_simulator: 'Candidate Simulator',
}

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || '未知'
}

export function releaseTypeLabel(type) {
  return RELEASE_TYPE_LABELS[type] || type || '未知'
}

export function statusClass(status) {
  if (['completed', 'published'].includes(status)) return 'text-emerald-600 bg-emerald-500/10'
  if (['failed', 'cancelled'].includes(status)) return 'text-destructive bg-destructive/10'
  if (['running', 'queued'].includes(status)) return 'text-amber-600 bg-amber-500/10'
  return 'text-muted-foreground bg-muted'
}

export function formatDate(value) {
  if (!value) return '—'
  const date = new Date(String(value).replace(' ', 'T') + (String(value).includes('Z') ? '' : 'Z'))
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function runProgress(run) {
  if (!run?.total_items) return 0
  return Math.round(((run.completed_items || 0) + (run.failed_items || 0)) / run.total_items * 100)
}

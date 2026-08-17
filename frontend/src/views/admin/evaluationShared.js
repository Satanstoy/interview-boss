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
  target: '被测版本',
  benchmark_suite: '评测题集',
  eval_protocol: '评测规则',
  judge: '评分模型',
  simulator_harness: '模拟面试执行器',
  candidate_simulator: '候选人模拟器',
}

export const EVALUATION_TARGETS = [
  {
    key: 'interview',
    label: '模拟面试 Agent',
    description: '通过多轮 E2E 验证面试流程、工具调用、追问和收尾质量。',
    status: 'available',
    statusLabel: '已支持',
    actionLabel: '可运行完整 E2E',
  },
  {
    key: 'experience_extraction',
    label: '面经提取 Agent',
    description: '从面试记录或文本中提取题目、主题和结构化经验。',
    status: 'planned',
    statusLabel: '待接入',
    actionLabel: '评测适配器待接入',
  },
  {
    key: 'resume_analysis',
    label: '简历分析 Agent',
    description: '分析简历证据、岗位匹配度和改进建议的完整性。',
    status: 'planned',
    statusLabel: '待接入',
    actionLabel: '评测适配器待接入',
  },
]

export const EVALUATION_FLOW_STEPS = [
  { key: 'releases', keys: ['EvalReleases', 'admin-evals-releases'], label: '版本与发布', description: '决定测谁', route: '/admin/evals/releases' },
  { key: 'benchmarks', keys: ['EvalBenchmarks', 'admin-evals-benchmarks'], label: 'Benchmark', description: '决定测什么', route: '/admin/evals/benchmarks' },
  { key: 'experiments', keys: ['EvalExperiments', 'admin-evals-experiments', 'admin-evals-run'], label: '测评实验', description: '启动完整 E2E', route: '/admin/evals/experiments' },
  { key: 'results', keys: ['EvalResults', 'admin-evals-results'], label: '评测结果', description: '看进度和结果', route: '/admin/evals/results' },
  { key: 'reviews', keys: ['EvalReviews', 'admin-evals-reviews'], label: '人工 A/B', description: '人工核验差异', route: '/admin/evals/reviews' },
]

export const RELEASE_TYPE_META = {
  target: { title: '被测版本', description: '待评测的 Agent、Workflow 或 Pipeline。' },
  benchmark_suite: { title: '评测题集', description: '固定的 Case、输入快照与质量要求。' },
  eval_protocol: { title: '评测规则', description: '重跑次数、聚合方式与通过门槛。' },
  judge: { title: '评分模型', description: '固定的 Judge Model 与评分 Prompt。' },
  simulator_harness: { title: '模拟面试执行器', description: '编排多轮 E2E、工具和轨迹采集。' },
  candidate_simulator: { title: '候选人模拟器', description: '生成候选人行为的模型与策略。' },
}

export const REVIEW_CHOICE_LABELS = {
  a: 'A 更好',
  b: 'B 更好',
  tie: '平局',
  both_fail: '都失败',
}

export const CHECK_STATUS_LABELS = {
  passed: '通过',
  failed: '失败',
  skipped: '跳过',
  pending: '待检查',
  invalid: '无效',
}

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || '未知'
}

export function releaseTypeLabel(type) {
  return RELEASE_TYPE_LABELS[type] || type || '未知'
}

export function releaseTypeMeta(type) {
  return RELEASE_TYPE_META[type] || { title: releaseTypeLabel(type), description: '评测运行依赖的版本化组件。' }
}

export function evaluationTargetLabel(type) {
  return EVALUATION_TARGETS.find(target => target.key === type)?.label || (type ? `未知评测对象（${type}）` : '未知评测对象')
}

export function checkStatusLabel(status) {
  return CHECK_STATUS_LABELS[status] || status || '未知'
}

export function reviewChoiceLabel(choice) {
  return REVIEW_CHOICE_LABELS[choice] || choice || '未选择'
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

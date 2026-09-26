/**
 * 预览模式（?preview=1）下保留预览参数。
 * 路由守卫对 admin 路由要求 is_admin，而预览模式会把当前用户置为非管理员预览用户，
 * 丢掉 preview 参数后返回类操作会被重定向到题库页。
 */
export function evalRouteLocation(path, query = {}) {
  return query.preview === '1' ? { path, query: { preview: '1' } } : path
}

export const STATUS_LABELS = {
  created: '待调度',
  queued: '排队中',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  expired: '已失效',
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

export const QUALITY_STATUS_LABELS = {
  pending: '质量待判定',
  passed: '质量通过',
  failed: '质量未通过',
  not_evaluated: '未完成质量评测',
}

export const RELEASE_TYPE_LABELS = {
  target: '被测版本',
  evaluation: '完整评测版本',
  benchmark_suite: '评测集',
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
    status: 'available',
    statusLabel: '已支持',
    actionLabel: '可运行结构化 Eval',
  },
  {
    key: 'jd_extraction',
    label: 'JD 提取 Agent',
    description: '从岗位描述中提取公司、岗位、薪资、技术要求和加分项。',
    status: 'available',
    statusLabel: '已支持',
    actionLabel: '可运行结构化 Eval',
  },
  {
    key: 'resume_analysis',
    label: '简历分析 / 优化 Agent',
    description: '评测简历事实保真、岗位匹配度和优化建议的可执行性。',
    status: 'available',
    statusLabel: '已支持',
    actionLabel: '可运行结构化 Eval',
  },
  {
    key: 'question_tagging',
    label: '面试题分类 Agent',
    description: '评测一级分类、二级分类、考点标签和难度标签的一致性。',
    status: 'available',
    statusLabel: '已支持',
    actionLabel: '可运行结构化 Eval',
  },
]

export const RELEASE_TYPE_META = {
  target: { title: '被测版本', description: '待评测的 Agent、Workflow 或 Pipeline。' },
  evaluation: { title: '完整评测版本', description: '一次评测所使用的题集、规则、模型、Harness 和模拟器整体版本。' },
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

export function qualityStatusLabel(status) {
  return QUALITY_STATUS_LABELS[status] || QUALITY_STATUS_LABELS.pending
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
  if (['failed', 'cancelled', 'expired'].includes(status)) return 'text-destructive bg-destructive/10'
  if (['running', 'queued'].includes(status)) return 'text-amber-600 bg-amber-500/10'
  return 'text-muted-foreground bg-muted'
}

export function formatDate(value) {
  if (!value) return '—'
  const date = new Date(String(value).replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function runProgress(run) {
  if (!run?.total_items) return 0
  return Math.round(((run.completed_items || 0) + (run.failed_items || 0)) / run.total_items * 100)
}

export function casePrioritySort(items) {
  if (!items) return []
  const priority = (item) => {
    if (item.outcome === 'failed') return 0
    if (item.outcome === 'poor') return 1
    if (item.status === 'failed') return 0
    if (item.status === 'completed' && item.hard_gate_status === 'failed') return 1
    if (item.status === 'completed' && item.judge_status === 'pending') return 2
    if (item.outcome === 'pending' || item.status === 'running' || item.status === 'queued') return 3
    return 4
  }
  return [...items].sort((a, b) => priority(a) - priority(b))
}


export const CASE_KEYBOARD_SHORTCUTS = {
  a: 'a',
  b: 'b',
  tie: 'tie',
  both_fail: 'both_fail',
}
export function scoreBarColorClass(score) {
  if (score == null) return 'bg-muted'
  if (score >= 0.8) return 'bg-emerald-500'
  if (score >= 0.5) return 'bg-amber-500'
  return 'bg-destructive'
}

/** 按失败率降序排列 by_target 数组 */
export function buildByTargetSort(byTarget) {
  const failureRate = (item) => {
    if (item?.distribution?.total) return item.distribution.failed / item.distribution.total
    return item.failed_count / Math.max(item.run_count, 1)
  }
  return [...byTarget].sort((a, b) => failureRate(b) - failureRate(a))
}

/** 计算通过率百分比 */
export function passRate(item) {
  if (!item.run_count) return 0
  return Math.round((item.passed_count / item.run_count) * 100)
}

export function pctLabel(value) {
  return value == null ? '—' : Math.round(value * 100) + '%'
}

export function inputSnapshotSummary(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return null
  const candidateView = snapshot.candidate_view || snapshot
  const harness = snapshot.harness_context || {}
  const profile = candidateView?.profile || candidateView?.resume || snapshot.profile || ''
  const behaviorInjections = harness.behavior_injections || snapshot.behavior_injections || {}
  return {
    profileSnippet: typeof profile === 'string' ? profile.slice(0, 120) : JSON.stringify(profile).slice(0, 120),
    hasProfile: Boolean(profile),
    difficulty: candidateView?.difficulty || snapshot.difficulty || '—',
    mode: candidateView?.mode || snapshot.mode || harness.mode || '—',
    opening: candidateView?.opening || snapshot.opening || harness.opening || '—',
    maxTurns: harness.max_turns ?? candidateView?.max_turns ?? snapshot.max_turns ?? '—',
    behaviorCount: Object.keys(behaviorInjections).length,
    totalKeys: Object.keys(snapshot).length,
  }
}

export function contractSummaryDetailed(contract) {
  if (!contract || typeof contract !== 'object') return null
  const hard = contract.hard_assertions || []
  const rubric = contract.rubric || {}
  const toolExp = contract.tool_expectations || {}
  const intentExp = contract.intent_expectations || []
  return {
    hardCount: hard.length,
    hardIds: hard.map(item => (typeof item === 'string' ? item : item.id || JSON.stringify(item))).slice(0, 8),
    rubricKeys: Object.keys(rubric),
    rubric,
    requiredTools: toolExp.required_tools || [],
    forbiddenTools: toolExp.forbidden_tools || [],
    minCalls: toolExp.min_calls ?? null,
    maxCalls: toolExp.max_calls ?? null,
    intentExpectationCount: Array.isArray(intentExp) ? intentExp.length : 0,
  }
}

export function judgeDetailsFromItem(item) {
  const score = item?.result?.score || {}
  const dimensions = score.dimensions || score.judge_dimensions || {}
  const dimEntries = Object.entries(dimensions).map(([key, val]) => ({
    key,
    score: val?.score ?? null,
    reasoning: val?.reasoning || val?.reason || '—',
    weight: val?.weight ?? null,
  }))
  return {
    judgeModel: score.judge_model || score.judgeModel || item?.judge_model || null,
    judgeScore: score.judge_score ?? score.judgeScore ?? score.score ?? null,
    reportedScore: score.judge_reported_score ?? score.reported_score ?? score.overall_score ?? null,
    weightedAvg: score.weighted_avg ?? score.weightedAvg ?? null,
    dimensions: dimEntries,
    criticalIssues: score.critical_issues || score.criticalIssues || [],
    highlights: score.highlights || [],
    error: score.error || null,
    judgeStatus: score.judge_status || item?.judge_status || null,
  }
}

export function scoreBreakdownFromItem(item) {
  const score = item?.result?.score || {}
  return {
    final: score.score ?? item?.score ?? null,
    deterministic: score.deterministic_score ?? score.deterministicScore ?? null,
    judge: score.judge_score ?? score.judgeScore ?? null,
    deterministicWeight: score.deterministic_weight ?? score.deterministicWeight ?? null,
    judgeWeight: score.judge_weight ?? score.judgeWeight ?? null,
    deterministicDimensions: score.deterministic_dimensions || score.deterministicDimensions || [],
    scoreSource: score.score_source || score.scoreSource || null,
  }
}

export function turnMetadata(turn) {
  const meta = turn?.metadata || {}
  const trace = meta.tool_calls_trace || meta.tool_calls || []
  const classify = meta.classify_result || {}
  const turnIntent = meta.turn_intent || {}
  return {
    toolCalls: Array.isArray(trace) ? trace : [],
    classify,
    turnIntent,
    selectedQuestion: meta.selected_question || null,
    questionSource: meta.question_source || meta.questionSource || null,
    hasSummary: meta.has_summary ?? meta.hasSummary ?? null,
    events: turn?.events || [],
  }
}

export function classifyItemQuality(item) {
  if (!item) return 'pending'
  const hardFailed = item.hard_gate_status === 'failed' || item.status === 'failed' || item.quality_status === 'failed'
  if (hardFailed) return 'failed'
  const score = item.score ?? item.result?.score?.score ?? item.result?.score?.final
  const judgeStatus = item.judge_status ?? item.result?.score?.judge_status
  const poorThreshold = item.quality_threshold ?? item.result?.quality_threshold ?? null
  if (poorThreshold != null && judgeStatus === 'succeeded' && score != null && Number(score) < Number(poorThreshold)) return 'poor'
  // Legacy payloads without a protocol threshold remain visible as passed/failed;
  // current APIs provide distribution from the Evaluation Release.
  if (item.hard_gate_status === 'passed' && score != null && poorThreshold != null && Number(score) < Number(poorThreshold)) return 'poor'
  if (item.hard_gate_status === 'passed' || item.contract_status === 'passed' || item.status === 'completed') return 'passed'
  if (item.status === 'running' || item.status === 'queued' || item.status === 'created') return 'pending'
  // pending judge or not evaluated -> if completed but no score yet, treat as pending for progress gap
  if (item.status === 'completed' && item.judge_status === 'pending') return 'pending'
  return item.status === 'completed' ? 'passed' : 'pending'
}

export function runDistribution(source) {
  if (source?.distribution) {
    const total = Number(source.distribution.total || 0)
    const counts = {
      passed: Number(source.distribution.passed || 0),
      poor: Number(source.distribution.poor || 0),
      failed: Number(source.distribution.failed || 0),
      pending: Number(source.distribution.pending || 0),
    }
    const pct = key => total ? Math.round(counts[key] / total * 100) : 0
    return { total, ...counts, pct: { passed: pct('passed'), poor: pct('poor'), failed: pct('failed'), pending: pct('pending') } }
  }
  const items = Array.isArray(source) ? source : (source?.items || [])
  const total = Array.isArray(source) ? items.length : (source?.total_items ?? items.length)
  if (!total) return { total: 0, passed: 0, poor: 0, failed: 0, pending: 0, pct: { passed: 0, poor: 0, failed: 0, pending: 0 } }
  const counts = { passed: 0, poor: 0, failed: 0, pending: 0 }
  for (const it of items) {
    const cls = classifyItemQuality(it)
    if (counts[cls] != null) counts[cls]++
    else counts.pending++
  }
  // 补齐 total 与 items 长度差（未拉取全量时）
  const accounted = counts.passed + counts.poor + counts.failed
  const pendingFromTotal = Math.max(0, total - accounted)
  // pending 取 max(已分类pending, 总量补齐)
  counts.pending = Math.max(counts.pending, pendingFromTotal)
  // 若三段和超总量（重复计数），规范化 pending
  if (counts.passed + counts.poor + counts.failed + counts.pending > total) {
    counts.pending = Math.max(0, total - counts.passed - counts.poor - counts.failed)
  }
  const pct = n => (total ? Math.round((n / total) * 100) : 0)
  // 修正四舍五入和≠100问题：最后一段补齐
  let pctPassed = pct(counts.passed)
  let pctPoor = pct(counts.poor)
  let pctFailed = pct(counts.failed)
  let pctPending = 100 - pctPassed - pctPoor - pctFailed
  if (total && pctPending < 0) pctPending = 0
  if (total && counts.pending === 0) pctPending = 0
  // 若 pending 为 0 但和≠100，微调 failed
  const sum = pctPassed + pctPoor + pctFailed + pctPending
  if (total && sum !== 100 && counts.pending > 0) {
    pctPending += 100 - sum
  } else if (total && sum !== 100) {
    pctFailed += 100 - sum
  }
  return { total, ...counts, pct: { passed: pctPassed, poor: pctPoor, failed: pctFailed, pending: pctPending } }
}

export const OUTCOME_LABELS = {
  failed: '失败',
  poor: '表现不佳',
  passed: '通过',
  pending: '未完成',
}

export function outcomeLabel(outcome) {
  return OUTCOME_LABELS[outcome] || '未完成'
}

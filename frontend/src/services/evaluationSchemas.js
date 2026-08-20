import { z } from 'zod'

const DistributionSchema = z.object({
  total: z.number().int().nonnegative().default(0),
  passed: z.number().int().nonnegative().default(0),
  poor: z.number().int().nonnegative().default(0),
  failed: z.number().int().nonnegative().default(0),
  pending: z.number().int().nonnegative().default(0),
})

const MetricCardSchema = z.object({
  key: z.string(),
  label: z.string(),
  unit: z.string(),
  direction: z.enum(['higher', 'lower']).optional(),
  value: z.unknown().nullable().optional(),
  threshold: z.number().nullable().optional(),
  status: z.string().optional(),
}).passthrough()

const AttentionCaseSchema = z.object({
  run_id: z.number().int(),
  item_id: z.number().int(),
  target_type: z.string(),
  case_key: z.string(),
  scenario_key: z.string().nullable().optional(),
  replication_index: z.number().int().nullable().optional(),
  score: z.number().nullable().optional(),
  outcome: z.enum(['failed', 'poor', 'pending']),
  primary_failure_reason: z.string(),
}).passthrough()

const RunSummarySchema = z.object({
  id: z.number().int(),
  status: z.string(),
  total_items: z.number().int().nonnegative().default(0),
  completed_items: z.number().int().nonnegative().default(0),
  failed_items: z.number().int().nonnegative().default(0),
  target_type: z.string().catch('unknown'),
  distribution: DistributionSchema,
  metric_cards: z.array(MetricCardSchema).default([]),
  attention_cases: z.array(AttentionCaseSchema).default([]),
}).passthrough()

const OverviewSchema = z.object({
  counts: z.record(z.number()).default({}),
  by_target: z.array(z.object({
    target_type: z.string().catch('unknown'),
    distribution: DistributionSchema,
  }).passthrough()).default([]),
}).passthrough()

const EvidenceSchema = z.object({
  schema_version: z.string(),
  run: z.object({
    id: z.number().int(),
    status: z.string(),
    quality_status: z.string(),
    target_type: z.string(),
    target_release_key: z.string().nullable().optional(),
    evaluation_release_key: z.string().nullable().optional(),
  }).passthrough(),
  item: z.object({
    id: z.number().int(),
    case_id: z.number().int().nullable().optional(),
    case_key: z.string(),
    score: z.number().nullable().optional(),
    primary_failure_reason: z.string().nullable().optional(),
  }).passthrough(),
  case: z.object({
    case_key: z.string(),
    scenario_key: z.string().nullable().optional(),
    input_digest: z.string().nullable().optional(),
    candidate_input: z.record(z.unknown()).default({}),
    admin_harness_context: z.record(z.unknown()).default({}),
    contract: z.record(z.unknown()).default({}),
  }).passthrough(),
  execution: z.object({
    status: z.string(),
    contract_status: z.string().nullable().optional(),
    hard_gate_status: z.string().nullable().optional(),
    judge_status: z.string().nullable().optional(),
    quality_status: z.string(),
  }).passthrough(),
  observation: z.object({
    status: z.string(),
    hard_assertions: z.array(z.record(z.unknown())).default([]),
    contract_violations: z.array(z.string()).default([]),
    target_payload: z.object({
      target_type: z.string(),
      payload_schema_version: z.string(),
      output: z.record(z.unknown()).default({}),
      trace: z.record(z.unknown()).default({}),
      metrics: z.record(z.unknown()).default({}),
    }).passthrough(),
  }).passthrough(),
  scoring: z.object({
    score: z.number().nullable().optional(),
    deterministic_score: z.number().nullable().optional(),
    judge_score: z.number().nullable().optional(),
    judge_status: z.string().nullable().optional(),
    details: z.record(z.unknown()).default({}),
  }).passthrough(),
  attempts: z.array(z.record(z.unknown())).default([]),
  artifacts: z.array(z.record(z.unknown())).default([]),
}).passthrough()

function defaultDistribution(run) {
  const total = Number(run?.total_items || 0)
  const completed = Number(run?.completed_items || 0)
  const failed = Number(run?.failed_items || 0)
  return { total, passed: 0, poor: 0, failed, pending: Math.max(0, total - completed - failed) }
}

export function normalizeRunSummary(run) {
  const value = { ...run }
  const parsed = RunSummarySchema.parse({
    ...value,
    distribution: value.distribution || defaultDistribution(value),
  })
  return { ...value, ...parsed }
}

export function normalizeEvaluationOverview(payload) {
  const value = { ...payload }
  const parsed = OverviewSchema.parse({
    ...value,
    by_target: (value.by_target || []).map(target => ({
      ...target,
      distribution: target.distribution || {
      total: 0,
      passed: 0,
      poor: 0,
      failed: 0,
      pending: 0,
      },
    })),
  })
  return { ...value, ...parsed }
}

export function parseCaseEvidenceView(payload) {
  const result = EvidenceSchema.safeParse(payload)
  if (!result.success) {
    const detail = result.error.issues.slice(0, 3).map(issue => issue.path.join('.')).join(', ')
    throw new Error(`评测证据格式不兼容${detail ? `：${detail}` : ''}`)
  }
  return result.data
}

export function normalizeCaseEvidenceForLegacyPanel(view) {
  const payload = view.observation.target_payload
  const mergedPayload = {
    ...payload.output,
    ...payload.trace,
    ...payload.metrics,
    metrics: payload.metrics,
  }
  const scoreDetails = view.scoring.details || {}
  const item = {
    ...view.item,
    replication_index: view.item.replication_index ?? 1,
    seed: view.item.seed ?? null,
    contract_status: view.execution.contract_status,
    hard_gate_status: view.execution.hard_gate_status,
    judge_status: view.execution.judge_status,
    result: {
      observation: {
        status: view.observation.status,
        payload: mergedPayload,
        hard_assertions: view.observation.hard_assertions,
        contract_violations: view.observation.contract_violations,
      },
      score: {
        ...scoreDetails,
        score: view.scoring.score,
        deterministic_score: view.scoring.deterministic_score,
        judge_score: view.scoring.judge_score,
        judge_status: view.scoring.judge_status,
      },
    },
  }
  return {
    ...view,
    item,
    case: {
      ...view.case,
      input_snapshot: {
        candidate_view: view.case.candidate_input,
        harness_context: view.case.admin_harness_context,
      },
      contract: view.case.contract,
    },
  }
}

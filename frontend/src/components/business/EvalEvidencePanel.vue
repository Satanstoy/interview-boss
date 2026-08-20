<script setup>
import { ref } from 'vue'
import { checkStatusLabel as checkLabel } from '@/views/admin/evaluationShared.js'
import {
  contractSummaryDetailed,
  inputSnapshotSummary,
  judgeDetailsFromItem,
  scoreBreakdownFromItem,
  turnMetadata,
} from '@/views/admin/evaluationShared.js'
import EvalScoreBar from '@/components/business/EvalScoreBar.vue'

defineProps({
  item: { type: Object, default: null },
  evidence: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

function turns(item) { return item?.result?.observation?.payload?.turns || [] }
function metrics(item) { return item?.result?.observation?.payload || {} }
function targetMetrics(item) { return item?.result?.observation?.payload?.metrics || {} }
function hardAssertions(item) { return item?.result?.observation?.hard_assertions || [] }
function assertionClass(passed) { return passed ? 'text-emerald-600 bg-emerald-500/10' : 'text-destructive bg-destructive/10' }
function pct(v) { return v == null ? '—' : Math.round(v * 100) + '%' }
function fmtScore(v) { return v == null ? '—' : Number(v).toFixed(3) }

/** 兼容旧 e2e：保留 */
function inputSummaryKeys(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return []
  const keys = Object.keys(snapshot)
  return keys.slice(0, 6)
}

function inputFieldLabel(key) {
  return { candidate_view: '候选人输入', harness_context: 'Harness 参数' }[key] || key
}
function contractSummary(contract) {
  if (!contract || typeof contract !== 'object') return null
  const hardCount = contract.hard_assertions?.length || 0
  const rubricKeys = Object.keys(contract.rubric || {})
  return { hardCount, rubricKeys }
}

const copied = ref('')
async function copyJson(data) {
  try {
    await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
    copied.value = JSON.stringify(data).slice(0, 20)
    setTimeout(() => { copied.value = '' }, 2000)
  } catch { /* ignore */ }
}

function scoreSourceLabel(source) {
  const map = {
    hybrid: '混合',
    deterministic_only: '仅规则',
    judge_only: '仅质量评审',
    deterministic_pending_judge: '待质量评审',
    judge_pending: '待质量评审',
    none: '无分数',
  }
  return map[source] || source || '—'
}

function questionSourceLabel(src) {
  if (!src) return '—'
  const m = { search: '搜索', draw: '抽取', retrieval: '检索', agent_internal: '内部', question_bank: '题库', search_questions: 'search_questions' }
  return m[src] || src
}

function targetPayload(evidence) {
  return evidence?.observation?.target_payload || null
}

function targetOutputLabel(targetType) {
  return {
    interview: '面试过程结果',
    experience_extraction: '面经提取结果',
    jd_extraction: '岗位信息提取结果',
    resume_analysis: '简历分析结果',
    question_tagging: '面试题分类结果',
  }[targetType] || '业务结果'
}

function outputFieldLabel(targetType, key) {
  const labels = {
    interview: { conversation_id: '对话编号', turns: '对话记录', errors: '执行错误' },
    experience_extraction: { doc_type: '内容类型', data: '提取内容', quality: '结果质量' },
    jd_extraction: { doc_type: '内容类型', data: '岗位信息', quality: '结果质量' },
    resume_analysis: { points: '优化建议', optimized_text: '优化后简历' },
    question_tagging: { tagged_rows: '分类结果', quality: '结果质量' },
  }
  return labels[targetType]?.[key] || key
}

function displayValue(value) {
  if (value == null || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function shortValue(value, limit = 40) {
  const text = displayValue(value)
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}
</script>

<template>
  <div aria-label="Case 证据面板" class="rounded-xl border border-border/60 bg-card">
    <!-- 顶部：当前 Case 标识 -->
    <div v-if="item" class="border-b border-border/60 px-4 py-3">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <span class="truncate font-medium">{{ item.case_key }}</span>
            <span v-if="evidence?.case?.scenario_key" class="hidden sm:inline truncate text-xs text-muted-foreground">/ {{ evidence.case.scenario_key }}</span>
            <span class="text-xs text-muted-foreground">第 {{ item.replication_index }} 次 · seed {{ item.seed }}</span>
          </div>
          <div class="mt-1 flex flex-wrap gap-2 text-xs">
            <span class="rounded-full bg-muted px-2 py-0.5">输出要求 {{ checkLabel(item.contract_status) }}</span>
            <span class="rounded-full bg-muted px-2 py-0.5">硬性要求 {{ checkLabel(item.hard_gate_status) }}</span>
            <span class="rounded-full bg-muted px-2 py-0.5">质量评审 {{ checkLabel(item.judge_status) }}</span>
            <span v-if="evidence?.case?.input_digest" class="hidden sm:inline rounded-full bg-muted px-2 py-0.5 font-mono text-[10px]">digest {{ String(evidence.case.input_digest).slice(0, 8) }}</span>
          </div>
        </div>
        <div class="shrink-0 text-right">
          <div v-if="item.score != null" class="text-xl font-semibold">{{ Number(item.score).toFixed(3) }}</div>
          <div v-if="scoreBreakdownFromItem(item).scoreSource" class="text-[10px] text-muted-foreground">{{ scoreSourceLabel(scoreBreakdownFromItem(item).scoreSource) }}</div>
        </div>
      </div>
    </div>

    <div v-if="!item" class="flex min-h-[240px] items-center justify-center text-sm text-muted-foreground">
      选择一个 Case 查看证据
    </div>

    <div v-else class="space-y-5 p-4 text-sm">
        <!-- P1: Case 概览卡 -->
        <section v-if="evidence?.case" aria-label="Case 概览">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">Case 概览</h3>
          <div class="rounded-xl border border-border/60 bg-card p-3">
            <div class="flex flex-wrap gap-2 text-xs">
              <span class="rounded-md bg-primary/10 px-2 py-1 font-mono">{{ evidence.case.case_key }}</span>
              <span v-if="evidence.case.scenario_key" class="rounded-md bg-muted px-2 py-1">场景 {{ evidence.case.scenario_key }}</span>
              <span class="rounded-md bg-muted px-2 py-1">replication #{{ item.replication_index }}</span>
              <span class="rounded-md bg-muted px-2 py-1">seed {{ item.seed }}</span>
              <span v-if="evidence.case.input_digest" class="rounded-md bg-muted px-2 py-1 font-mono text-[10px]">input {{ String(evidence.case.input_digest).slice(0, 12) }}</span>
            </div>

            <!-- 输入摘要 -->
            <div v-if="inputSnapshotSummary(evidence.case.input_snapshot)" class="mt-3">
              <div class="mb-1 text-xs font-medium">输入摘要</div>
              <div class="grid gap-2 sm:grid-cols-2 text-xs">
                <div class="rounded-md bg-muted/50 p-2">
                  <div class="text-muted-foreground">难度 / 模式 / 轮数</div>
                  <div class="mt-1 font-medium">{{ inputSnapshotSummary(evidence.case.input_snapshot).difficulty }} · {{ inputSnapshotSummary(evidence.case.input_snapshot).mode }} · {{ inputSnapshotSummary(evidence.case.input_snapshot).maxTurns }} 轮</div>
                  <div v-if="inputSnapshotSummary(evidence.case.input_snapshot).behaviorCount" class="mt-1 text-muted-foreground">行为注入 {{ inputSnapshotSummary(evidence.case.input_snapshot).behaviorCount }} 条</div>
                </div>
                <div class="rounded-md bg-muted/50 p-2">
                  <div class="text-muted-foreground">开场白</div>
                  <div class="mt-1 line-clamp-2 whitespace-pre-wrap">{{ inputSnapshotSummary(evidence.case.input_snapshot).opening || '—' }}</div>
                </div>
              </div>
              <div v-if="inputSnapshotSummary(evidence.case.input_snapshot).hasProfile" class="mt-2 rounded-md bg-muted/30 p-2 text-xs">
                <div class="text-muted-foreground">候选人画像（前 120 字）</div>
                <div class="mt-1 line-clamp-3 whitespace-pre-wrap leading-relaxed">{{ inputSnapshotSummary(evidence.case.input_snapshot).profileSnippet }}{{ (evidence.case.input_snapshot?.candidate_view?.profile || '').length > 120 ? '…' : '' }}</div>
              </div>
              <!-- 保留 e2e 兼容的旧“候选人可见输入”标签云（用于既有断言） -->
              <div class="mt-2 flex flex-wrap gap-1.5">
                <span class="text-[10px] text-muted-foreground">候选人可见输入 ·</span>
                <span v-for="key in inputSummaryKeys(evidence.case?.input_snapshot)" :key="key" class="rounded-md bg-muted px-2 py-0.5 text-[10px]">
                  <span class="text-muted-foreground">{{ inputFieldLabel(key) }}:</span> {{ shortValue(evidence.case.input_snapshot[key], 28) }}
                </span>
              </div>
            </div>

            <!-- 契约摘要 -->
            <div v-if="contractSummaryDetailed(evidence.case.contract)" class="mt-3">
              <div class="mb-1 text-xs font-medium">输出要求摘要</div>
              <div class="flex flex-wrap gap-1.5 text-xs">
                <span class="rounded-md bg-muted px-2 py-1">硬断言 {{ contractSummaryDetailed(evidence.case.contract).hardCount }} 项</span>
                <span v-for="k in contractSummaryDetailed(evidence.case.contract).rubricKeys.slice(0, 6)" :key="k" class="rounded-md bg-muted px-2 py-1">{{ k }}</span>
                <span v-if="contractSummaryDetailed(evidence.case.contract).requiredTools.length" class="rounded-md bg-blue-500/10 px-2 py-1 text-blue-700">必需 {{ contractSummaryDetailed(evidence.case.contract).requiredTools.join(', ') }}</span>
                <span v-if="contractSummaryDetailed(evidence.case.contract).forbiddenTools.length" class="rounded-md bg-destructive/10 px-2 py-1 text-destructive">禁止 {{ contractSummaryDetailed(evidence.case.contract).forbiddenTools.join(', ') }}</span>
                <span v-if="contractSummaryDetailed(evidence.case.contract).intentExpectationCount" class="rounded-md bg-amber-500/10 px-2 py-1 text-amber-700">意图期望 {{ contractSummaryDetailed(evidence.case.contract).intentExpectationCount }} 轮</span>
              </div>
            </div>

            <!-- 分数概览条 -->
            <div v-if="scoreBreakdownFromItem(item).final != null || scoreBreakdownFromItem(item).deterministic != null || scoreBreakdownFromItem(item).judge != null" class="mt-3">
              <div class="mb-1 flex items-center justify-between text-xs">
                <span class="font-medium">分数分解</span>
                <span class="text-muted-foreground">规则检查 {{ fmtScore(scoreBreakdownFromItem(item).deterministic) }} · 质量评审 {{ fmtScore(scoreBreakdownFromItem(item).judge) }} · 最终 {{ fmtScore(scoreBreakdownFromItem(item).final) }}</span>
              </div>
              <EvalScoreBar :deterministic="scoreBreakdownFromItem(item).deterministic" :judge="scoreBreakdownFromItem(item).judge" :final="scoreBreakdownFromItem(item).final" height="h-2.5" />
              <div class="mt-1.5 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
                <span v-if="scoreBreakdownFromItem(item).scoreSource" class="rounded bg-muted px-1.5 py-0.5">{{ scoreSourceLabel(scoreBreakdownFromItem(item).scoreSource) }}</span>
                <span v-if="scoreBreakdownFromItem(item).deterministicWeight != null" class="rounded bg-muted px-1.5 py-0.5">权重 硬性要求 {{ Math.round(scoreBreakdownFromItem(item).deterministicWeight * 100) }}% · 质量评审 {{ Math.round(scoreBreakdownFromItem(item).judgeWeight * 100) }}%</span>
                <span v-if="scoreBreakdownFromItem(item).deterministicDimensions.length" class="rounded bg-muted px-1.5 py-0.5">维度 {{ scoreBreakdownFromItem(item).deterministicDimensions.join(' · ') }}</span>
              </div>
            </div>
          </div>
        </section>

        <section v-if="targetPayload(evidence) && Object.keys(targetPayload(evidence).output || {}).length" aria-label="业务结果">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">{{ targetOutputLabel(targetPayload(evidence).target_type) }}</h3>
          <div class="rounded-xl border border-border/60 bg-card p-3">
            <div class="grid gap-2 sm:grid-cols-2">
              <div v-for="(value, key) in targetPayload(evidence).output" :key="key" class="rounded-md bg-muted/40 p-2">
                <div class="text-xs text-muted-foreground">{{ outputFieldLabel(targetPayload(evidence).target_type, key) }}</div>
                <pre class="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs leading-relaxed">{{ displayValue(value) }}</pre>
              </div>
            </div>
          </div>
        </section>

        <!-- P2: 对话记录增强 -->
        <section v-if="turns(item).length" aria-label="对话记录">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">对话记录 · {{ turns(item).length }} 轮</h3>
          <div class="space-y-3">
            <div v-for="turn in turns(item)" :key="turn.turn" class="space-y-2">
              <div class="flex justify-end"><div class="max-w-[85%] rounded-lg rounded-tr-none bg-primary/10 px-3 py-2 text-xs"><div class="mb-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground"><span>候选人 · 第 {{ turn.turn }} 轮</span><span v-if="turnMetadata(turn).questionSource" class="rounded bg-background px-1 py-0.5">{{ questionSourceLabel(turnMetadata(turn).questionSource) }}</span></div><div class="whitespace-pre-wrap leading-relaxed">{{ turn.user }}</div></div></div>
              <div class="flex justify-start"><div class="max-w-[85%] rounded-lg rounded-tl-none bg-muted px-3 py-2 text-xs"><div class="mb-0.5 text-[10px] text-muted-foreground">面试官 / Agent <span v-if="turnMetadata(turn).selectedQuestion">· 已选 {{ turnMetadata(turn).selectedQuestion.id || '题目' }}</span></div><div class="whitespace-pre-wrap leading-relaxed">{{ turn.assistant }}</div></div></div>

              <!-- 每轮元数据折叠 -->
              <details v-if="turnMetadata(turn).toolCalls.length || Object.keys(turnMetadata(turn).classify).length || Object.keys(turnMetadata(turn).turnIntent).length || turnMetadata(turn).events.length" class="rounded-lg border border-border/60 bg-card px-3 py-2 text-xs">
                <summary class="cursor-pointer text-xs font-medium text-muted-foreground">本轮元数据 · {{ turnMetadata(turn).toolCalls.length }} 工具 · {{ turnMetadata(turn).events.length }} 事件</summary>
                <div class="mt-2 space-y-2">
                  <div v-if="turnMetadata(turn).toolCalls.length">
                    <div class="text-[10px] font-medium text-muted-foreground">工具调用</div>
                    <div class="mt-1 space-y-1">
                      <div v-for="(tc, idx) in turnMetadata(turn).toolCalls" :key="idx" class="flex flex-wrap items-center gap-1.5 rounded-md bg-muted/50 px-2 py-1 text-[11px]">
                        <span class="font-mono font-medium">{{ tc.tool_name || tc.step || 'tool' }}</span>
                        <span :class="['rounded-full px-1.5 py-0.5 text-[10px]', tc.ok === false ? 'bg-destructive/10 text-destructive' : 'bg-emerald-500/10 text-emerald-700']">{{ tc.ok === false ? '失败' : '成功' }}</span>
                        <span v-if="tc.result_count != null" class="text-muted-foreground">{{ tc.result_count }} 结果</span>
                        <span v-if="tc.elapsed_ms" class="text-muted-foreground">{{ tc.elapsed_ms }}ms</span>
                        <span v-if="tc.fallback_used" class="rounded bg-amber-500/10 px-1 py-0.5 text-amber-700">fallback</span>
                      </div>
                    </div>
                  </div>
                  <div v-if="Object.keys(turnMetadata(turn).classify).length">
                    <div class="text-[10px] font-medium text-muted-foreground">意图分类</div>
                    <div class="mt-1 flex flex-wrap gap-1.5 text-[11px]">
                      <span v-if="turnMetadata(turn).classify.intent" class="rounded-md bg-muted px-2 py-1">intent {{ turnMetadata(turn).classify.intent }}</span>
                      <span v-if="turnMetadata(turn).classify.candidate_act" class="rounded-md bg-muted px-2 py-1">行为 {{ turnMetadata(turn).classify.candidate_act }}</span>
                      <span v-if="turnMetadata(turn).classify.should_retrieve != null" class="rounded-md bg-muted px-2 py-1">需检索 {{ turnMetadata(turn).classify.should_retrieve ? '是' : '否' }}</span>
                      <span v-if="turnMetadata(turn).classify.requires_question_bank != null || turnMetadata(turn).classify.requires_bank_question != null" class="rounded-md bg-muted px-2 py-1">需题库 {{ (turnMetadata(turn).classify.requires_question_bank ?? turnMetadata(turn).classify.requires_bank_question) ? '是' : '否' }}</span>
                    </div>
                  </div>
                  <div v-if="Object.keys(turnMetadata(turn).turnIntent).length">
                    <div class="text-[10px] font-medium text-muted-foreground">决策策略</div>
                    <div class="mt-1 flex flex-wrap gap-1.5 text-[11px]">
                      <span v-if="turnMetadata(turn).turnIntent.strategy" class="rounded-md bg-muted px-2 py-1">策略 {{ turnMetadata(turn).turnIntent.strategy }}</span>
                      <span v-if="turnMetadata(turn).turnIntent.tool_intent" class="rounded-md bg-muted px-2 py-1">工具意图 {{ JSON.stringify(turnMetadata(turn).turnIntent.tool_intent).slice(0, 60) }}</span>
                      <span v-if="turnMetadata(turn).hasSummary != null" class="rounded-md bg-muted px-2 py-1">has_summary {{ String(turnMetadata(turn).hasSummary) }}</span>
                    </div>
                  </div>
                  <div v-if="turnMetadata(turn).events.length">
                    <div class="text-[10px] font-medium text-muted-foreground">Pipeline 事件 · {{ turnMetadata(turn).events.length }}</div>
                    <div class="mt-1 max-h-28 overflow-auto rounded-md bg-muted/30 p-2 text-[10px] font-mono leading-relaxed">
                      <div v-for="(ev, ei) in turnMetadata(turn).events.slice(0, 12)" :key="ei" class="truncate">{{ ev.type || ev.step || 'event' }} {{ (ev.data && JSON.stringify(ev.data).slice(0, 80)) || '' }}</div>
                      <div v-if="turnMetadata(turn).events.length > 12" class="text-muted-foreground">… 还有 {{ turnMetadata(turn).events.length - 12 }} 条</div>
                    </div>
                  </div>
                </div>
              </details>
            </div>
          </div>
        </section>

        <!-- P3: Harness 执行指标（工具/意图/抽取 三组） -->
        <section v-if="Object.keys(metrics(item)).length" aria-label="评测执行指标">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">评测执行指标</h3>
          <div class="space-y-3">
            <!-- 工具调用详情 -->
            <div v-if="metrics(item).tool_metrics" class="rounded-xl border border-border/60 bg-card p-3">
              <div class="flex items-center justify-between">
                <div class="text-xs font-medium">工具使用效果</div>
                <div class="text-xs text-muted-foreground">{{ metrics(item).tool_metrics.call_count || 0 }} 次调用 · {{ metrics(item).tool_metrics.failed_call_count || 0 }} 次失败</div>
              </div>
              <div class="mt-2 flex flex-wrap gap-1.5 text-xs">
                <span v-if="metrics(item).tool_metrics.tool_names?.length" class="rounded-md bg-muted px-2 py-1">已调 {{ metrics(item).tool_metrics.tool_names.join(', ') }}</span>
                <span v-if="metrics(item).tool_metrics.required_tools?.length" class="rounded-md bg-muted px-2 py-1">必需 {{ metrics(item).tool_metrics.required_tools.join(', ') || '—' }}</span>
                <span v-if="metrics(item).tool_metrics.required_tools_missing?.length" class="rounded-md bg-destructive/10 px-2 py-1 text-destructive">缺失 {{ metrics(item).tool_metrics.required_tools_missing.join(', ') }}</span>
                <span v-else-if="metrics(item).tool_metrics.required_tools?.length" class="rounded-md bg-emerald-500/10 px-2 py-1 text-emerald-700">必需齐全</span>
                <span v-if="metrics(item).tool_metrics.forbidden_tools_used?.length" class="rounded-md bg-destructive/10 px-2 py-1 text-destructive">禁用被调 {{ metrics(item).tool_metrics.forbidden_tools_used.join(', ') }}</span>
                <span class="rounded-md px-2 py-1 text-xs" :class="metrics(item).tool_metrics.result_used ? 'bg-emerald-500/10 text-emerald-700' : 'bg-amber-500/10 text-amber-700'">结果{{ metrics(item).tool_metrics.result_used ? '已使用' : '未使用' }}</span>
              </div>
              <!-- 逐轮调用列表 -->
              <div v-if="metrics(item).tool_calls?.length || metrics(item).tool_metrics.tool_names?.length" class="mt-2">
                <div v-if="metrics(item).tool_calls?.length" class="space-y-1">
                  <div v-for="(c, i) in metrics(item).tool_calls" :key="i" class="flex flex-wrap items-center gap-2 rounded-md bg-muted/40 px-2 py-1.5 text-xs">
                    <span class="font-mono font-medium">{{ c.tool_name }}</span>
                    <span class="text-muted-foreground">第 {{ c.turn }} 轮</span>
                    <span :class="['rounded-full px-1.5 py-0.5 text-[10px]', c.ok === false ? 'bg-destructive/10 text-destructive' : 'bg-emerald-500/10 text-emerald-700']">{{ c.ok === false ? '失败' : '成功' }}</span>
                    <span v-if="c.result_count != null" class="text-muted-foreground">{{ c.result_count }} 结果</span>
                    <span v-if="c.elapsed_ms" class="text-muted-foreground">{{ c.elapsed_ms }}ms</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 意图识别详情 -->
            <div v-if="metrics(item).intent_metrics" class="rounded-xl border border-border/60 bg-card p-3">
              <div class="flex items-center justify-between">
                <div class="text-xs font-medium">用户意图理解效果</div>
                <div class="text-xs text-muted-foreground">覆盖 {{ pct(metrics(item).intent_metrics.intent_coverage) }} · 准确 {{ pct(metrics(item).intent_metrics.accuracy) }} · 策略覆盖 {{ pct(metrics(item).intent_metrics.strategy_coverage) }}</div>
              </div>
              <div class="mt-2 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
                <span class="rounded bg-muted px-1.5 py-0.5">评测 {{ metrics(item).intent_metrics.evaluated_count }} 轮</span>
                <span class="rounded bg-muted px-1.5 py-0.5">失败 {{ metrics(item).intent_metrics.failed_count }} 轮</span>
                <span class="rounded bg-muted px-1.5 py-0.5">观测 {{ metrics(item).intent_metrics.observed_turn_count }} 轮</span>
                <span v-if="metrics(item).intent_metrics.missing_intent_count" class="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-700">缺失意图 {{ metrics(item).intent_metrics.missing_intent_count }}</span>
              </div>
              <div v-if="metrics(item).intent_metrics.results?.length" class="mt-3 overflow-x-auto -mx-1 px-1">
                <table class="min-w-[560px] w-full text-xs">
                  <thead class="text-[11px] text-muted-foreground">
                    <tr class="border-b border-border/60"><th class="px-2 py-1 text-left">轮</th><th class="px-2 py-1 text-left">期望</th><th class="px-2 py-1 text-left">实际</th><th class="px-2 py-1 text-left">结果</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="r in metrics(item).intent_metrics.results" :key="r.turn" class="border-b border-border/30 last:border-0">
                      <td class="px-2 py-1.5 font-mono">#{{ r.turn }}</td>
                      <td class="px-2 py-1.5"><span class="rounded bg-muted px-1.5 py-0.5 text-[11px]">{{ r.expected?.expected_intent || r.expected?.intent || '—' }}</span><span v-if="r.expected?.expected_candidate_act" class="ml-1 rounded bg-muted px-1.5 py-0.5 text-[11px]">{{ r.expected.expected_candidate_act }}</span><span v-if="r.expected?.expected_strategy" class="ml-1 rounded bg-muted px-1.5 py-0.5 text-[11px]">{{ r.expected.expected_strategy }}</span></td>
                      <td class="px-2 py-1.5"><span class="rounded bg-muted px-1.5 py-0.5 text-[11px]">{{ r.actual?.intent || '—' }}</span><span v-if="r.actual?.candidate_act" class="ml-1 rounded bg-muted px-1.5 py-0.5 text-[11px]">{{ r.actual.candidate_act }}</span><span v-if="r.actual?.strategy" class="ml-1 rounded bg-muted px-1.5 py-0.5 text-[11px]">{{ r.actual.strategy }}</span></td>
                      <td class="px-2 py-1.5"><span :class="['rounded-full px-2 py-0.5 text-[10px]', r.passed ? 'bg-emerald-500/10 text-emerald-700' : 'bg-destructive/10 text-destructive']">{{ r.passed ? '通过' : '失败' }}</span><div v-if="r.failures?.length" class="mt-1 text-[10px] text-destructive">{{ r.failures.join(' · ') }}</div></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="metrics(item).intent_records?.length" class="mt-2">
                <details class="text-xs">
                  <summary class="cursor-pointer text-muted-foreground">查看每轮意图记录 · {{ metrics(item).intent_records.length }} 条</summary>
                  <div class="mt-2 space-y-1">
                    <div v-for="rec in metrics(item).intent_records" :key="rec.turn" class="rounded-md bg-muted/40 px-2 py-1.5 text-[11px]">第 {{ rec.turn }} 轮 · intent {{ rec.intent || '—' }} · 行为 {{ rec.candidate_act || '—' }} · 策略 {{ rec.strategy || '—' }}</div>
                  </div>
                </details>
              </div>
            </div>

            <!-- 结构化抽取详情 -->
            <div v-if="targetMetrics(item).field_coverage != null || targetMetrics(item).question_recall != null || targetMetrics(item).source_fact_coverage != null || targetMetrics(item).target_alignment != null || targetMetrics(item).taxonomy_validity != null || targetMetrics(item).field_results?.length || targetMetrics(item).label_results?.length" class="rounded-xl border border-border/60 bg-card p-3">
              <div class="text-xs font-medium">结构化抽取详情</div>
              <div class="mt-2 grid gap-2 sm:grid-cols-2 text-xs">
                <div v-if="targetMetrics(item).field_coverage != null" class="rounded-md bg-muted/40 p-2"><div class="text-muted-foreground">字段覆盖</div><div class="mt-1 font-mono font-medium">{{ pct(targetMetrics(item).field_coverage) }} <span class="text-muted-foreground">· 匹配 {{ pct(targetMetrics(item).field_match_rate) }}</span></div></div>
                <div v-if="targetMetrics(item).question_recall != null" class="rounded-md bg-muted/40 p-2"><div class="text-muted-foreground">题目召回 / 精确</div><div class="mt-1 font-mono font-medium">{{ pct(targetMetrics(item).question_recall) }} / {{ pct(targetMetrics(item).question_precision) }}</div></div>
                <div v-if="targetMetrics(item).source_fact_coverage != null" class="rounded-md bg-muted/40 p-2"><div class="text-muted-foreground">简历事实覆盖</div><div class="mt-1 font-mono font-medium">{{ pct(targetMetrics(item).source_fact_coverage) }}</div></div>
                <div v-if="targetMetrics(item).target_alignment != null" class="rounded-md bg-muted/40 p-2"><div class="text-muted-foreground">岗位匹配</div><div class="mt-1 font-mono font-medium">{{ pct(targetMetrics(item).target_alignment) }}</div></div>
                <div v-if="targetMetrics(item).taxonomy_validity != null" class="rounded-md bg-muted/40 p-2"><div class="text-muted-foreground">分类有效性</div><div class="mt-1 font-mono font-medium">{{ pct(targetMetrics(item).taxonomy_validity) }} <span class="text-muted-foreground">· 准确 {{ pct(targetMetrics(item).classification_accuracy) }}</span></div></div>
              </div>
              <div v-if="targetMetrics(item).field_results?.length" class="mt-3 overflow-x-auto -mx-1 px-1">
                <table class="min-w-[560px] w-full text-xs">
                  <thead class="text-[11px] text-muted-foreground"><tr class="border-b border-border/60"><th class="px-2 py-1 text-left">字段</th><th class="px-2 py-1 text-left">期望</th><th class="px-2 py-1 text-left">实际</th><th class="px-2 py-1 text-left">结果</th></tr></thead>
                  <tbody>
                    <tr v-for="(fr, i) in targetMetrics(item).field_results" :key="i" class="border-b border-border/30 last:border-0">
                      <td class="px-2 py-1.5 font-mono text-[11px]">{{ fr.path }}</td>
                      <td class="px-2 py-1.5 truncate max-w-[120px]">{{ shortValue(fr.expected, 40) }}</td>
                      <td class="px-2 py-1.5 truncate max-w-[120px]">{{ shortValue(fr.actual, 40) }}</td>
                      <td class="px-2 py-1.5"><span :class="['rounded-full px-2 py-0.5 text-[10px]', fr.passed ? 'bg-emerald-500/10 text-emerald-700' : 'bg-destructive/10 text-destructive']">{{ fr.passed ? '通过' : '失败' }}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div v-if="targetMetrics(item).label_results?.length" class="mt-3">
                <div class="text-[11px] font-medium text-muted-foreground">分类标签结果 · {{ targetMetrics(item).label_results.length }}</div>
                <div class="mt-1 space-y-1">
                  <div v-for="(lr, i) in targetMetrics(item).label_results.slice(0, 10)" :key="i" class="flex items-center gap-2 rounded-md bg-muted/40 px-2 py-1 text-xs"><span class="truncate">{{ lr.question }}</span><span :class="['ml-auto rounded-full px-1.5 py-0.5 text-[10px]', lr.passed ? 'bg-emerald-500/10 text-emerald-700' : 'bg-destructive/10 text-destructive']">{{ lr.passed ? '通过' : '失败' }}</span></div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 硬性要求断言 -->
        <section v-if="hardAssertions(item).length" aria-label="硬性要求">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">硬性要求 · {{ hardAssertions(item).length }} 项</h3>
          <div class="space-y-2">
            <div v-for="a in hardAssertions(item)" :key="a.id" :class="['rounded-lg border p-2.5 text-xs', a.passed ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-destructive/30 bg-destructive/5']">
              <span :class="['rounded-full px-2 py-0.5 text-[10px]', assertionClass(a.passed)]">{{ a.passed ? '通过' : '失败' }}</span>
              <span class="ml-2 font-medium">{{ a.id }}</span>
              <div class="mt-1 text-muted-foreground">{{ a.evidence }}</div>
            </div>
          </div>
        </section>

        <!-- P4: 固定质量评审（维度表 + issues/highlights） -->
        <section v-if="item.result?.score" aria-label="固定质量评审">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">固定质量评审</h3>
          <div class="rounded-xl border border-border/60 bg-card p-3">
            <div class="flex flex-wrap items-center gap-2 text-xs">
              <span v-if="judgeDetailsFromItem(item).judgeModel" class="rounded-md bg-muted px-2 py-1 font-mono text-[11px]">{{ judgeDetailsFromItem(item).judgeModel }}</span>
              <span v-if="judgeDetailsFromItem(item).judgeScore != null" class="rounded-md bg-primary/10 px-2 py-1">评审分 <span class="font-mono font-medium">{{ Number(judgeDetailsFromItem(item).judgeScore).toFixed(3) }}</span></span>
              <span v-if="judgeDetailsFromItem(item).weightedAvg != null" class="rounded-md bg-muted px-2 py-1">加权均分 {{ judgeDetailsFromItem(item).weightedAvg }}</span>
              <span v-if="judgeDetailsFromItem(item).reportedScore != null" class="rounded-md bg-muted px-2 py-1">原始分 {{ Number(judgeDetailsFromItem(item).reportedScore).toFixed(3) }}</span>
              <span v-if="judgeDetailsFromItem(item).judgeStatus" class="rounded-full bg-muted px-2 py-0.5 text-[10px]">{{ checkLabel(judgeDetailsFromItem(item).judgeStatus) }}</span>
            </div>
            <div v-if="judgeDetailsFromItem(item).error" class="mt-2 rounded-md bg-destructive/10 p-2 text-xs text-destructive">质量评审失败：{{ judgeDetailsFromItem(item).error }}</div>

            <!-- 维度分数表 -->
            <div v-if="judgeDetailsFromItem(item).dimensions.length" class="mt-3 overflow-auto">
              <table class="w-full text-xs">
                <thead class="text-[11px] text-muted-foreground"><tr class="border-b border-border/60"><th class="px-2 py-1 text-left">维度</th><th class="px-2 py-1 text-center">分数</th><th class="px-2 py-1 text-center">权重</th><th class="px-2 py-1 text-left">推理</th></tr></thead>
                <tbody>
                  <tr v-for="dim in judgeDetailsFromItem(item).dimensions" :key="dim.key" class="border-b border-border/30 last:border-0">
                    <td class="px-2 py-2 font-medium">{{ dim.key }}</td>
                    <td class="px-2 py-2 text-center"><span :class="['rounded-full px-2 py-0.5 font-mono text-xs', dim.score >= 4 ? 'bg-emerald-500/10 text-emerald-700' : dim.score >= 3 ? 'bg-amber-500/10 text-amber-700' : 'bg-destructive/10 text-destructive']">{{ dim.score }}/5</span></td>
                    <td class="px-2 py-2 text-center font-mono text-muted-foreground">{{ dim.weight != null ? (dim.weight * 100).toFixed(0) + '%' : '—' }}</td>
                    <td class="px-2 py-2 max-w-[260px] whitespace-pre-wrap leading-relaxed text-muted-foreground">{{ dim.reasoning }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="mt-2 text-xs text-muted-foreground">暂无维度明细</div>

            <div v-if="judgeDetailsFromItem(item).criticalIssues.length" class="mt-3">
              <div class="text-xs font-medium text-destructive">关键问题 · {{ judgeDetailsFromItem(item).criticalIssues.length }}</div>
              <ul class="mt-1 list-disc space-y-1 pl-5 text-xs text-destructive">
                <li v-for="(ci, i) in judgeDetailsFromItem(item).criticalIssues" :key="i" class="leading-relaxed">{{ ci }}</li>
              </ul>
            </div>
            <div v-if="judgeDetailsFromItem(item).highlights.length" class="mt-3">
              <div class="text-xs font-medium text-emerald-700">亮点 · {{ judgeDetailsFromItem(item).highlights.length }}</div>
              <ul class="mt-1 list-disc space-y-1 pl-5 text-xs text-emerald-700">
                <li v-for="(hl, i) in judgeDetailsFromItem(item).highlights" :key="i" class="leading-relaxed">{{ hl }}</li>
              </ul>
            </div>
          </div>
        </section>

        <!-- P6: 输出要求详情（结构化） -->
        <section v-if="evidence?.case?.contract" aria-label="输出要求详情">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">输出要求详情</h3>
          <div class="rounded-xl border border-border/60 bg-card p-3 text-xs">
            <div class="grid gap-3 sm:grid-cols-2">
              <div>
                <div class="text-[11px] font-medium text-muted-foreground">硬性要求 · {{ (evidence.case.contract.hard_assertions || []).length }} 项</div>
                <div class="mt-1 flex flex-wrap gap-1.5">
                  <span v-for="ha in (evidence.case.contract.hard_assertions || []).slice(0, 10)" :key="ha.id || ha" class="rounded-md bg-muted px-2 py-1 font-mono text-[11px]">{{ ha.id || ha }}</span>
                  <span v-if="(evidence.case.contract.hard_assertions || []).length > 10" class="text-muted-foreground">+{{ (evidence.case.contract.hard_assertions.length - 10) }} 项</span>
                </div>
              </div>
              <div>
                <div class="text-[11px] font-medium text-muted-foreground">评分维度 · {{ Object.keys(evidence.case.contract.rubric || {}).length }}</div>
                <div class="mt-1 flex flex-wrap gap-1.5">
                  <span v-for="(cfg, key) in (evidence.case.contract.rubric || {})" :key="key" class="rounded-md bg-muted px-2 py-1">{{ key }} <span class="text-muted-foreground">{{ cfg.weight != null ? Math.round(cfg.weight * 100) + '%' : '' }}</span></span>
                </div>
              </div>
            </div>
            <div v-if="evidence.case.contract.tool_expectations" class="mt-3 rounded-md bg-muted/40 p-2">
              <div class="text-[11px] font-medium">工具期望</div>
              <div class="mt-1 flex flex-wrap gap-1.5 text-[11px]">
                <span v-if="evidence.case.contract.tool_expectations.required_tools?.length" class="rounded bg-background px-2 py-1">必需 {{ evidence.case.contract.tool_expectations.required_tools.join(', ') }}</span>
                <span v-if="evidence.case.contract.tool_expectations.forbidden_tools?.length" class="rounded bg-destructive/10 px-2 py-1 text-destructive">禁止 {{ evidence.case.contract.tool_expectations.forbidden_tools.join(', ') }}</span>
                <span class="rounded bg-background px-2 py-1">调用 {{ evidence.case.contract.tool_expectations.min_calls ?? 0 }} – {{ evidence.case.contract.tool_expectations.max_calls ?? '∞' }}</span>
                <span class="rounded bg-background px-2 py-1">最多失败 {{ evidence.case.contract.tool_expectations.max_failed_calls ?? 0 }}</span>
                <span v-if="evidence.case.contract.tool_expectations.require_result_used" class="rounded bg-amber-500/10 px-2 py-1 text-amber-700">要求结果被使用</span>
              </div>
            </div>
            <div v-if="evidence.case.contract.intent_expectations?.length" class="mt-3">
              <div class="text-[11px] font-medium text-muted-foreground">意图期望 · {{ evidence.case.contract.intent_expectations.length }} 轮</div>
              <div class="mt-1 overflow-auto">
                <table class="w-full text-[11px]">
                  <thead class="text-muted-foreground"><tr class="border-b border-border/60"><th class="px-2 py-1 text-left">轮</th><th class="px-2 py-1 text-left">期望意图</th><th class="px-2 py-1 text-left">期望行为</th><th class="px-2 py-1 text-left">策略</th><th class="px-2 py-1 text-left">需题库</th></tr></thead>
                  <tbody>
                    <tr v-for="ie in evidence.case.contract.intent_expectations" :key="ie.turn" class="border-b border-border/30 last:border-0">
                      <td class="px-2 py-1.5 font-mono">#{{ ie.turn }}</td>
                      <td class="px-2 py-1.5">{{ ie.expected_intent || ie.expectedIntent || '—' }}</td>
                      <td class="px-2 py-1.5">{{ ie.expected_candidate_act || ie.expectedCandidateAct || '—' }}</td>
                      <td class="px-2 py-1.5">{{ ie.expected_strategy || ie.expectedStrategy || '—' }}</td>
                      <td class="px-2 py-1.5">{{ ie.requires_question_bank == null ? '—' : (ie.requires_question_bank ? '是' : '否') }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-if="evidence.case.contract.expected_questions?.length" class="mt-3">
              <div class="text-[11px] font-medium text-muted-foreground">期望题目 · {{ evidence.case.contract.expected_questions.length }}</div>
              <div class="mt-1 space-y-1">
                <div v-for="(q, i) in evidence.case.contract.expected_questions.slice(0, 6)" :key="i" class="rounded bg-muted/40 px-2 py-1">{{ String(q).slice(0, 80) }}</div>
              </div>
            </div>
          </div>
        </section>

        <!-- 高级详情（保留兼容，结构化展示 + 一键复制） -->
        <details class="rounded-lg border border-border/60 px-3 py-2" open>
          <summary class="cursor-pointer text-xs font-medium text-muted-foreground">高级详情（输入快照 / 输出要求 / 执行尝试 / 文件证据）</summary>
          <div class="mt-3 space-y-3">
            <!-- 候选人可见输入 -->
            <div v-if="evidence">
              <div class="mb-1 text-xs font-medium">候选人可见输入</div>
              <div class="flex flex-wrap gap-1.5 mb-2">
                <span v-for="key in inputSummaryKeys(evidence.case?.input_snapshot)" :key="key" class="rounded-md bg-muted px-2 py-1 text-xs">
                  <span class="text-muted-foreground">{{ inputFieldLabel(key) }}:</span> {{ shortValue(evidence.case.input_snapshot[key], 40) }}
                </span>
              </div>
              <details class="text-xs">
                <summary class="cursor-pointer text-muted-foreground hover:text-foreground">查看完整 JSON</summary>
                <div class="relative mt-1">
                  <button type="button" class="absolute top-1 right-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground" @click="copyJson(evidence.case?.input_snapshot)">{{ copied === JSON.stringify(evidence.case?.input_snapshot).slice(0, 20) ? '已复制' : '复制' }}</button>
                  <pre class="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-muted-foreground">{{ JSON.stringify(evidence.case?.input_snapshot || {}, null, 2) }}</pre>
                </div>
              </details>
            </div>
            <!-- 输出要求技术详情 -->
            <div v-if="evidence">
              <div class="mb-1 text-xs font-medium">输出要求（技术详情）</div>
              <div v-if="contractSummary(evidence.case?.contract)" class="flex flex-wrap gap-1.5 mb-2">
                <span class="rounded-md bg-muted px-2 py-1 text-xs">硬断言 {{ contractSummary(evidence.case.contract).hardCount }} 项</span>
                <span v-for="key in contractSummary(evidence.case.contract).rubricKeys.slice(0, 4)" :key="key" class="rounded-md bg-muted px-2 py-1 text-xs">{{ key }}</span>
              </div>
              <details class="text-xs">
                <summary class="cursor-pointer text-muted-foreground hover:text-foreground">查看完整 JSON</summary>
                <div class="relative mt-1">
                  <button type="button" class="absolute top-1 right-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground" @click="copyJson(evidence.case?.contract)">{{ copied === JSON.stringify(evidence.case?.contract).slice(0, 20) ? '已复制' : '复制' }}</button>
                  <pre class="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-muted-foreground">{{ JSON.stringify(evidence.case?.contract || {}, null, 2) }}</pre>
                </div>
              </details>
            </div>
            <!-- Attempt 记录 -->
            <div v-if="evidence?.attempts?.length">
              <div class="mb-1 text-xs font-medium">执行尝试记录</div>
              <div v-for="attempt in evidence.attempts" :key="attempt.id" class="rounded-md bg-muted/40 p-2 text-xs mb-2">
                <div class="font-medium">Attempt #{{ attempt.attempt_index }} · {{ attempt.status }}</div>
                <details class="mt-1">
                  <summary class="cursor-pointer text-muted-foreground hover:text-foreground">查看原始观察</summary>
                  <div class="relative mt-1">
                    <button type="button" class="absolute top-1 right-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground" @click="copyJson(attempt.raw_observation)">复制</button>
                    <pre class="max-h-28 overflow-auto whitespace-pre-wrap text-muted-foreground">{{ JSON.stringify(attempt.raw_observation || {}, null, 2) }}</pre>
                  </div>
                </details>
              </div>
            </div>
            <!-- Artifact 索引 -->
            <div v-if="evidence?.artifacts?.length">
              <div class="mb-1 text-xs font-medium">文件证据索引</div>
              <div v-for="artifact in evidence.artifacts" :key="artifact.id" class="text-xs text-muted-foreground">{{ artifact.artifact_type }} · {{ artifact.storage_path }}</div>
            </div>
          </div>
        </details>
      </div>
  </div>
</template>

<script setup>
import { ScrollArea } from '@/components/ui/scroll-area'
import { checkStatusLabel as checkLabel } from '@/views/admin/evaluationShared.js'

defineProps({
  item: { type: Object, default: null },
  evidence: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

function turns(item) { return item?.result?.observation?.payload?.turns || [] }
function metrics(item) { return item?.result?.observation?.payload || {} }
function hardAssertions(item) { return item?.result?.observation?.hard_assertions || [] }
function assertionClass(passed) { return passed ? 'text-emerald-600 bg-emerald-500/10' : 'text-destructive bg-destructive/10' }
function pct(v) { return v == null ? '—' : Math.round(v * 100) + '%' }
</script>

<template>
  <div aria-label="Case 证据面板" class="flex h-full flex-col">
    <!-- 顶部：当前 Case 标识 -->
    <div v-if="item" class="shrink-0 border-b border-border/60 px-4 py-3">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <span class="truncate font-medium">{{ item.case_key }}</span>
            <span class="text-xs text-muted-foreground">第 {{ item.replication_index }} 次 · seed {{ item.seed }}</span>
          </div>
          <div class="mt-1 flex flex-wrap gap-2 text-xs">
            <span class="rounded-full bg-muted px-2 py-0.5">契约 {{ checkLabel(item.contract_status) }}</span>
            <span class="rounded-full bg-muted px-2 py-0.5">硬门禁 {{ checkLabel(item.hard_gate_status) }}</span>
            <span class="rounded-full bg-muted px-2 py-0.5">Judge {{ checkLabel(item.judge_status) }}</span>
          </div>
        </div>
        <div class="shrink-0 text-right">
          <div v-if="item.score != null" class="text-xl font-semibold">{{ Number(item.score).toFixed(3) }}</div>
        </div>
      </div>
    </div>

    <div v-if="!item" class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
      选择一个 Case 查看证据
    </div>

    <ScrollArea v-else class="flex-1">
      <div class="space-y-4 p-4 text-sm">
        <!-- 对话智能渲染 -->
        <section v-if="turns(item).length" aria-label="对话记录">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">对话记录</h3>
          <div class="space-y-2">
            <div v-for="turn in turns(item)" :key="turn.turn" class="space-y-2">
              <div class="flex justify-end"><div class="max-w-[85%] rounded-lg rounded-tr-none bg-primary/10 px-3 py-2 text-xs"><div class="mb-0.5 text-[10px] text-muted-foreground">候选人 · 第 {{ turn.turn }} 轮</div><div class="whitespace-pre-wrap leading-relaxed">{{ turn.user }}</div></div></div>
              <div class="flex justify-start"><div class="max-w-[85%] rounded-lg rounded-tl-none bg-muted px-3 py-2 text-xs"><div class="mb-0.5 text-[10px] text-muted-foreground">面试官 / Agent</div><div class="whitespace-pre-wrap leading-relaxed">{{ turn.assistant }}</div></div></div>
            </div>
          </div>
        </section>

        <!-- 确定性指标卡片 -->
        <section v-if="Object.keys(metrics(item)).length" aria-label="确定性指标">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">确定性指标</h3>
          <div class="grid gap-2 sm:grid-cols-2">
            <div v-if="metrics(item).tool_metrics" class="rounded-lg border border-border/60 p-3"><div class="font-medium">工具调用</div><div class="mt-1 text-xs text-muted-foreground">{{ metrics(item).tool_metrics.call_count || 0 }} 次调用 · {{ metrics(item).tool_metrics.failed_call_count || 0 }} 次失败</div></div>
            <div v-if="metrics(item).intent_metrics" class="rounded-lg border border-border/60 p-3"><div class="font-medium">意图识别</div><div class="mt-1 text-xs text-muted-foreground">覆盖率 {{ pct(metrics(item).intent_metrics.intent_coverage) }} · 准确率 {{ pct(metrics(item).intent_metrics.accuracy) }}</div></div>
            <div v-if="metrics(item).metrics?.field_coverage != null" class="rounded-lg border border-border/60 p-3"><div class="font-medium">结构化抽取</div><div class="mt-1 text-xs text-muted-foreground">字段覆盖 {{ pct(metrics(item).metrics.field_coverage) }} · 题目召回 {{ pct(metrics(item).metrics.question_recall) }}</div></div>
            <div v-if="metrics(item).metrics?.source_fact_coverage != null" class="rounded-lg border border-border/60 p-3"><div class="font-medium">简历事实与岗位</div><div class="mt-1 text-xs text-muted-foreground">事实覆盖 {{ pct(metrics(item).metrics.source_fact_coverage) }} · 岗位匹配 {{ pct(metrics(item).metrics.target_alignment) }}</div></div>
          </div>
        </section>

        <!-- 硬门禁断言 -->
        <section v-if="hardAssertions(item).length" aria-label="硬门禁">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">硬门禁</h3>
          <div class="space-y-2">
            <div v-for="a in hardAssertions(item)" :key="a.id" :class="['rounded-lg border p-2.5 text-xs', a.passed ? 'border-emerald-500/30' : 'border-destructive/30']">
              <span :class="['rounded-full px-2 py-0.5 text-[10px]', assertionClass(a.passed)]">{{ a.passed ? '通过' : '失败' }}</span>
              <span class="ml-2 font-medium">{{ a.id }}</span>
              <div class="mt-1 text-muted-foreground">{{ a.evidence }}</div>
            </div>
          </div>
        </section>

        <!-- Judge 评分 -->
        <section v-if="item.result?.score" aria-label="Judge 评分">
          <h3 class="mb-2 text-xs font-semibold text-muted-foreground">Judge 评分</h3>
          <div class="rounded-lg border border-border/60 p-3">
            <div v-if="item.result.score.judge_score != null" class="text-sm">Judge 分：<span class="font-mono font-medium">{{ Number(item.result.score.judge_score).toFixed(3) }}</span></div>
          </div>
        </section>

        <!-- 高级详情（evidence 增强） -->
        <details class="rounded-lg border border-border/60 px-3 py-2">
          <summary class="cursor-pointer text-xs font-medium text-muted-foreground">高级详情（输入快照 / 契约 / Attempt / Artifact）</summary>
          <div class="mt-3 space-y-3">
            <div v-if="evidence"><div class="mb-1 text-xs font-medium">候选人可见输入</div><pre class="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">{{ JSON.stringify(evidence.case?.input_snapshot || {}, null, 2) }}</pre></div>
            <div v-if="evidence"><div class="mb-1 text-xs font-medium">确定性契约</div><pre class="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">{{ JSON.stringify(evidence.case?.contract || {}, null, 2) }}</pre></div>
            <div v-if="evidence?.attempts?.length"><div class="mb-1 text-xs font-medium">Attempt 记录</div><div v-for="attempt in evidence.attempts" :key="attempt.id" class="rounded-md bg-muted/40 p-2 text-xs"><div class="font-medium">Attempt #{{ attempt.attempt_index }} · {{ attempt.status }}</div><pre class="mt-1 max-h-28 overflow-auto whitespace-pre-wrap text-muted-foreground">{{ JSON.stringify(attempt.raw_observation || {}, null, 2) }}</pre></div></div>
            <div v-if="evidence?.artifacts?.length"><div class="mb-1 text-xs font-medium">Artifact 索引</div><div v-for="artifact in evidence.artifacts" :key="artifact.id" class="text-xs text-muted-foreground">{{ artifact.artifact_type }} · {{ artifact.storage_path }}</div></div>
          </div>
        </details>
      </div>
    </ScrollArea>
  </div>
</template>
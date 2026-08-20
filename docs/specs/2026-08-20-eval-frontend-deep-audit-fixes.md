# Spec: 评测中心前端深度审计修复 — 2026-08-20

> 位置: `frontend/src/views/admin/Evaluation*.vue` + `frontend/src/components/business/Eval*.vue` + `frontend/src/services/evaluationApi.js` + `frontend/src/layouts/AuthenticatedLayout.vue`
> 类型: 前端布局/交互/视觉/可访问性深度修复
> 日期: 2026-08-20
> 状态: 待实施
> 审计依据: 用户现场反馈2项 + `docs/specs/2026-08-19-eval-evidence-visibility-gap.md` 6阶段刚上线后的回归 + 代码走读 `D15 UX / D16 craft / D14 correctness / D13 setup`
> 原则: 先止血（P0布局锁死/窄条/进度条误导）→ 再一致性 → 再抛光；每个 Task 2-5分钟可独立交付，TDD/先写失败用例

---

## 背景

- `2026-08-19` 刚完成 `EvalEvidencePanel` 6阶段补全（`h/493` 行，`Vue:74→~500`）：Case概览/对话元数据/确定性三组/Judge维度/分数分解/契约详情。首屏信息量翻3倍，暴露了原 `flex-col h-full + overflow-hidden` 布局的脆弱性。
- 用户反馈2项必现：
  1. **Run详情页完全无法上下滚动，首屏以下内容不可见**（`EvaluationRunView`）。
  2. **“最近评测运行”每行被压成窄条**（`EvaluationResultsView:165` 用 `Button` 当列表行）。
- 顺带把 `EvalProgressBar` 的“单色百分比”误导修掉：14条里 `7通过/3表现不佳/3失败/1未跑`，当前只显示单一进度，无法一眼看分布。

---

## 目标/非目标

**目标**
- Run详情与人工A/B两页恢复正常滚动，`390px/1280px/1600px` + 放大字号均可用。
- 最近运行/批量实验列表恢复卡片宽度，`shadcn Button` 仅作操作。
- 进度条从“单值”改为“分段分布”：`通过(绿)/表现不佳(黄)/失败(红)/未跑(留空)`，14条示例正确分段。
- 清掉同类债：响应式溢出、路由key残留、SSE泄漏、表格可读性、a11y色独、文案过期、`has()` 兼容。

**非目标**
- 不改后端聚合口径（`deterministic/judge/hard_gate` 判定口径沿用 `evaluationShared.js` 现有）；不引入新依赖；不改 `backend/data`。

---

## 现状核实（已读源码）

| 文件 | 行号 | 现象 | 后果 |
|------|------|------|------|
| `EvaluationRunView.vue:177,218,276` | `flex flex-col h-full` + `summary在flex-1外` + `EvalEvidencePanel:ScrollArea flex-1` | 外层 `AuthenticatedLayout:760 overflow-hidden` 关死，summary不固定高度把工作区挤到0 | 首屏以下被“吃掉” |
| `EvaluationReviewsView.vue:147,170,190` | 同构 + `h-[calc(100vh-340px)]` 硬编码 | 窄屏/放大字号溢出 | 同病 |
| `EvaluationResultsView.vue:165-188` | `Button variant=ghost size=sm class="flex w-full flex-col"` 当行 | `inline-flex justify-center h-9` 与 `flex-col` 冲突 | 窄药丸 |
| `EvaluationExperimentsView.vue:230` | `xl:grid-cols-[minmax(0,500px)_...]` | `500px` 硬阈值 | `390px` 横向溢出 |
| `EvalEvidencePanel.vue:265-311` | 表 `w-full` + `max-w-[120px] truncate`截到40字 | 期望/实际不可辨 | 可读性0 |
| `AuthenticatedLayout.vue:763` | `:key="route.name \|\| route.path"` | 切 `runs/12→13` 不重挂 | 旧证据残留 |
| `EvaluationRunView.vue:27,83,171` | `new AbortController()`在setup顶层 + `while(!aborted && !terminal)` | 切路由后仍回调 `load()` | 泄漏/重连风暴 |
| `EvalProgressBar.vue:17-34` | 两段 `absolute left-0` 叠盖，`final`用`left` | 颜色/刻度错 | 误导 |
| `evaluationShared.js:141` | `new Date(str+'Z')` | 已带Z的ISO回退原串 | 偶现`—` |
| `EvaluationFlowNav.vue:24` | 文案含已删 `Benchmark` | 与 `73-78` 4步不一致 | 迷惑 |

---

## 方案总览（Milestones）

| 里程碑 | 标题 | 严重度 | 工作量 | 校验 |
|--------|------|--------|--------|------|
| M-1 | 恢复滚动：Run/Reviews 去 `flex-col h-full`，改自然页滚 | 🔴 | 30m | 3视口+键盘j/k |
| M-2 | 行宽修复：Results/Experiment行去 `Button`，改原生 | 🔴 | 20m | 列表宽度=容器宽度 |
| M-3 | 分段进度条：`绿/黄/红/留空` + 14条示例 | 🔴 | 1h | 单元+Playwright |
| M-4 | 响应式/表格可读性：grid阈值+表min-w+卡片视图 | 🟡 | 45m | 390px截图 |
| M-5 | 路由/SSE/日期健壮性 | 🟡 | 30m | 切Run/SSE断线 |
| M-6 | a11y/文案/`has()`兼容 | 🟢 | 20m | axe/FF121- |
| M-7 | 收敛：确认 `2026-08-19` 的8个 Task 无回退 | 🟢 | 15m | `npm run build` |

---

## M-1 恢复滚动（P0）

**Files:**
- Edit: `frontend/src/views/admin/EvaluationRunView.vue`
- Edit: `frontend/src/views/admin/EvaluationReviewsView.vue`
- Edit: `frontend/src/components/business/EvalEvidencePanel.vue`

**Step 1 — RunView 改页滚**
```vue
// 之前 :177 <div class="flex flex-col h-full">
<div class="h-full overflow-y-auto custom-scrollbar custom-scrollbar-always">
  <div class="mx-auto max-w-[1600px] px-4 py-4"> <!-- header+summary+阶段 -->
  <div class="mx-auto max-w-[1600px] px-4 pb-6"> <!-- 工作区不再 flex-1 -->
    <div class="hidden lg:block w-72 shrink-0"><!-- 导航 -->
    <div class="min-w-0 flex-1"><!-- 证据 -->
```
删 `flex-1 min-h-0` 工作区hack；`EvalEvidencePanel` 去 `ScrollArea` 或保留但加 `min-h-[320px]` 兜底。

**Step 2 — ReviewsView 同改**
`147 <div class="flex flex-col h-full">` → `h-full overflow-y-auto`；`190 h-[calc(100vh-340px)]` → `min-h-[400px] flex-1`，外层统管滚动。

**Step 3 — 验证**
`Playwright` 视口 `1280×800/390×844/1600×900 + 150%` 字号，断言 `Case概览/分数汇总/导航` 均可 `scrollIntoView`；`j/k` 切Case后证据区`scrollTop`归零。

**Step 4 — 提交** `fix(frontend): restore page scroll in Run/Reviews detail`

---

## M-2 行宽修复（P0）

**Files:**
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue:165,186,197`
- Edit: `frontend/src/views/admin/EvaluationExperimentView.vue:120-128`（若仍有Button行）

**Step 1**
```vue
<!-- 之前 -->
<Button v-for="run" variant="ghost" size="sm" class="flex w-full flex-col">
<!-- 之后 -->
<button type="button" v-for="run" class="flex w-full min-w-0 flex-col gap-3 rounded-lg border border-transparent p-4 text-left hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-4">
```
右侧 `w-48` → `w-full sm:w-52 shrink-0 min-w-0`；批量实验行已是原生`button`，保持。

**Step 2 — 验证** 行宽 `=== 容器宽度 - padding`；`sm` 断点下左右两列对齐。

**Step 3 — 提交** `fix(frontend): fix narrow rows by not using Button as list row`

---

## M-3 分段进度条（P0）— 通过绿/不佳黄/失败红/未跑留空

**现状**
`EvalProgressBar.vue` 只支持单值 `value%` + 单色；`EvaluationRunView:32 progressStats()` 已有 `passed/failed/running/judgePending` 但未分“黄”。调用方 `runProgress()` 按 `(completed+failed)/total` 算单值，14条`7/3/3/1`只显示`~71%`，看不出`3黄`。

**口径定义**（前端判定，不改后端）
- **通过(绿)**：`status=completed && hard_gate=passed && (judge_status=succeeded ? score>=0.5 : true)` 或 `hard_gate=passed` 且非黄/红
- **表现不佳(黄)**：`hard_gate=passed && judge_status=succeeded && score<0.6` 且 `contract_status!=failed`（可阈值化，后续抽 `THRESHOLDS.poor=0.6`）
- **失败(红)**：`hard_gate=failed` 或 `status=failed` 或 `quality_status=failed`
- **未跑(留空)**：`total - (绿+黄+红)`，对应 `muted` 底色，不占段
> `poor/failed/passed` 三者互斥，计数和`===total`；`judgePending/running`归“未跑”或单列提示，不进三色。

**Files:**
- Edit: `frontend/src/components/business/EvalProgressBar.vue`（新增分段模式，向后兼容单值）
- Edit: `frontend/src/views/admin/evaluationShared.js`（新增 `classifyItemQuality(item)` + `runDistribution(runOrItems)`）
- Edit: `frontend/src/views/admin/EvaluationRunView.vue:32,197-206`
- Edit: `frontend/src/views/admin/EvaluationExperimentView.vue:107,126`
- Edit: `frontend/src/views/admin/EvaluationOverviewView.vue:85`（可选，byTarget卡用分段）
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue:143,186`（同）

**Step 1 — 共享判定**
```js
// evaluationShared.js
export const PROGRESS_THRESHOLDS = { poor: 0.6 } // 黄阈值，后续可配置
export function classifyItemQuality(item) {
  const hardFailed = item.hard_gate_status === 'failed' || item.status === 'failed'
  if (hardFailed) return 'failed'
  const score = item.score ?? item.result?.score?.score
  if (item.judge_status === 'succeeded' && score != null && score < PROGRESS_THRESHOLDS.poor) return 'poor'
  if (item.hard_gate_status === 'passed' || item.contract_status === 'passed') return 'passed'
  if (item.status === 'completed') return 'passed' // 兜底
  return 'pending' // 未跑/进行中
}
export function runDistribution(source) {
  const items = Array.isArray(source) ? source : (source.items || [])
  const total = Array.isArray(source) ? items.length : (source.total_items ?? items.length)
  const counts = { passed:0, poor:0, failed:0, pending:0 }
  for (const it of items) counts[classifyItemQuality(it)]++
  // 若 total 来自 run.total_items 但 items 未全量，pending 补齐
  counts.pending = Math.max(0, total - counts.passed - counts.poor - counts.failed)
  const pct = n => total ? Math.round(n/total*100) : 0
  return { total, ...counts, pct: { passed:pct(counts.passed), poor:pct(counts.poor), failed:pct(counts.failed), pending:pct(counts.pending) } }
}
```

**Step 2 — 进度条分段模式**
```vue
<!-- EvalProgressBar.vue props 新增 -->
segments: { type: Array, default: null } // [{key:'passed', value:7, color:'bg-emerald-500'}, ...]
<!-- 渲染分支 -->
<template>
  <div v-if="segments" role="progressbar" :aria-label="`进度 ${total}：通过${passed} 不佳${poor} 失败${failed} 未跑${pending}`" class="flex h-2 w-full overflow-hidden rounded-full bg-muted">
    <div v-for="seg in segments.filter(s=>s.value>0)" :key="seg.key" :class="[seg.color, 'h-full']" :style="{ width: seg.pct + '%' }" :title="`${seg.label} ${seg.value}/${total}`" />
  </div>
  <div v-else>…原单值逻辑保留…</div>
  <!-- 图例（可选 showLegend） -->
  <div v-if="segments && showLegend" class="mt-1.5 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
    <span class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-emerald-500"/>通过 {{counts.passed}}</span>
    <span class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-amber-500"/>不佳 {{counts.poor}}</span>
    <span class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-destructive"/>失败 {{counts.failed}}</span>
    <span v-if="counts.pending" class="inline-flex items-center gap-1"><span class="size-2 rounded-full bg-muted-foreground/30"/>未跑 {{counts.pending}}</span>
  </div>
</template>
```
颜色：`passed bg-emerald-500`、`poor bg-amber-500`、`failed bg-destructive`、`pending` 留空（底 `bg-muted` 透出）。`aria` 需包含四段数值。

**Step 3 — 调用方改单值→分段**
```vue
// EvaluationRunView.vue:206 之前
<EvalProgressBar :value="progress" size="sm" />
// 之后
<EvalProgressBar :segments="progressSegments" show-legend size="sm" />
// script
const dist = computed(() => runDistribution(run.value))
const progressSegments = computed(() => [
  { key:'passed', label:'通过', value: dist.value.passed, pct: dist.value.pct.passed, color:'bg-emerald-500' },
  { key:'poor', label:'不佳', value: dist.value.poor, pct: dist.value.pct.poor, color:'bg-amber-500' },
  { key:'failed', label:'失败', value: dist.value.failed, pct: dist.value.pct.failed, color:'bg-destructive' },
])
// 摘要行 197-201 保留文字，同时加图例
```
`EvaluationResultsView:143,186 / ExperimentView:107,126` 同改；`total=0` 时显示 `—`；`poor阈值` 可抽 `frontend/src/constants/evalThresholds.js` 但首版先放 `evaluationShared.js` 常量。

**Step 4 — 14条示例验收**
- 造 `total=14 items=[7 passed, 3 poor(score=0.45), 3 failed(hard_gate failed), 1 pending]`，渲染后三段宽度 `50%/21%/21%`（四舍五入后和`≈100`，pending留空`7%`），图例 `7/3/3/1`，`role=progressbar` 的 `aria-label` 含四数。
- 边界：`total=0 → —`；`score==null → 不进黄`；`hardFailed 优先于黄`。

**Step 5 — 验证**
- `node -e` 单测 `classifyItemQuality/runDistribution`（7/3/3/1、0、边界）。
- `Playwright`: `runs/12` 详情页分段条可见且三色俱全，`results` 列表每行条与图例一致，`390px` 下不换行错位。

**Step 6 — 提交** `feat(frontend): segmented progress bar (green/amber/red + pending gap) for 7/3/3/1`

---

## M-4 响应式与表格可读性（P1）

**Files:**
- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue:230`
- Edit: `frontend/src/components/business/EvalEvidencePanel.vue:190,265-311`
- Edit: `frontend/src/views/admin/EvaluationReleasesView.vue:90-92,101`

**Step 1 — grid阈值**
`xl:grid-cols-[minmax(0,500px)_...]` → `minmax(280px,520px)`，并给两侧 `AppCard` 补 `min-w-0`。

**Step 2 — 表可读性**
证据面板意图/抽取表外层 `overflow-x-auto -mx-4 px-4`，表设 `min-w-[560px]`；移动下切卡片视图（`sm:hidden` 卡 + `hidden sm:table`）。

**Step 3 — Releases表**
`table-fixed` 保留但 `release_key` 加 `title`，`Benchmark` 展开行 `colspan` 内层 `grid` 加 `min-w-0`。

**Step 4 — 验证** `390/768/1280` 截图无横向溢出；意图 `expected vs actual` 不再截到不可辨。

**Step 5 — 提交** `fix(frontend): responsive grid and table readability in eval`

---

## M-5 路由/SSE/日期健壮性（P1）

**Files:**
- Edit: `frontend/src/layouts/AuthenticatedLayout.vue:763`
- Edit: `frontend/src/views/admin/EvaluationRunView.vue:27,83,171`
- Edit: `frontend/src/views/admin/EvaluationExperimentView.vue:44`
- Edit: `frontend/src/views/admin/evaluationShared.js:141`

**Step 1 — key**
`:key="route.name || route.path"` → `:key="route.fullPath"`；或在两详情页加 `watch(()=>route.params.runId/experimentId, load)`。

**Step 2 — SSE**
`watchEvents` 返回可取消句柄，`onUnmounted` 同步 `abort` + 设 `stopped=true` 哨兵，`load()`回调前判 `stopped`。

**Step 3 — 日期**
`formatDate` 改 `const d=new Date(value); return isNaN(d)?value:d.toLocaleString('zh-CN',{hour12:false})`，不再自补`Z`。

**Step 4 — 验证** 切 `runs/12→13` 数据即时换；断网 `SSE` 重连不泄漏；`Z`/空格日期均可显。

**Step 5 — 提交** `fix(frontend): route key/SSE abort and date parsing robustness`

---

## M-6 a11y/文案/has()兼容（P2）

**Files:**
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue:153-159`
- Edit: `frontend/src/components/business/EvalCaseNavigator.vue:68`
- Edit: `frontend/src/views/admin/EvaluationFlowNav.vue:24`
- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue:289-291`

**Step 1** 筛选按钮补 `aria-pressed`，`CaseNavigator` 补 `role=listbox/option` + `aria-selected`，选中态加 `✓` 文字。
**Step 2** `FlowNav:24` 文案删 `Benchmark →`，与 `EVALUATION_FLOW_STEPS` 四步对齐。
**Step 3** `has-[:checked]` 改 `:class` 条件，兼容 `FF<121`。
**Step 4 — 提交** `fix(frontend): a11y and copy for eval nav/filters`

---

## M-7 回归确认（P2）

**Files:**
- Read-only check: 上述未覆盖但 `2026-08-19` 已修的 `M-1..M-8`（Select/Checkbox/Badge/EvalScoreBar/import位置/filteredItems等）无回退。

**Step 1** `cd frontend && npm run build` + `npx eslint src/views/admin/Evaluation*.vue src/components/business/Eval*.vue`
**Step 2** `npx playwright test tests/e2e/eval-workspace.spec.js tests/e2e/evaluation-center-readable.spec.js`
**Step 3 — 提交** `chore(frontend): verify no regression from 2026-08-19 fixes`

---

## 验收标准

1. **滚动**：Run/Reviews两详情页在三视口+150%字号下首屏以下可滚，无第二滚动条嵌套。
2. **行宽**：Results/Experiment行宽度===容器宽度，窄药丸消失。
3. **分段条**：14条`7/3/3/1`正确分 `绿50/黄21/红21/空7`，图例与`aria-label`四数齐全；`total=0`显示`—`；`hardFailed`优先。
4. **响应式**：`390px`无横向溢出，表在移动端可横滚或切卡片。
5. **健壮**：切Run即换数据；SSE切走不泄漏；日期`Z`不丢。
6. **无回退**：`2026-08-19`的8个Milestone仍绿，`build/eslint`零新增告警。

---

## 风险

| 风险 | 缓解 |
|------|------|
| `poor`阈值`0.6`与后端“不佳”口径不一致 | 口径抽常量`PROGRESS_THRESHOLDS`，先前端判定，后续对齐后端`quality_status` |
| 分段条四舍五入和`≠100%` | 按 `pct = round(n/total*100)`，最后一段 `100 - sum(前N-1)` 补齐 |
| `has()`改`class`后选中态样式漂移 | 保留原`border-primary/bg-primary/5`两类，视觉回归截图对比 |

---

## 参考

- `docs/specs/2026-08-19-eval-frontend-ui-ux-fixes.md:16,49,160,194`（历史5个未import + 进度条复用）
- `docs/specs/2026-08-19-eval-evidence-visibility-gap.md:295`（6阶段刚上线，首屏信息量触发滚动债）
- `frontend/src/components/business/EvalProgressBar.vue:17,32,42`（单值实现）
- `frontend/src/layouts/AuthenticatedLayout.vue:760`（`overflow-hidden` 隔离）


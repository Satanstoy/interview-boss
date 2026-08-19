# Spec: 评测中心前端 UI/UX 修复 — tech-audit 2026-08-19

> 位置: `frontend/src/views/admin/Evaluation*.vue` + `frontend/src/components/business/Eval*.vue`
> 类型: 前端缺陷修复 + 结构优化 + 视觉一致性
> 日期: 2026-08-19
> 状态: 待实施
> 审计依据: tech-audit quick scan（D1, D14, D15, D16）+ findings.tsv 2026-08-19
> 原则: TDD（先写失败测试）→ 最小实现 → 验证 → 提交
> 方法: 里程碑按严重度排序；每个 Task 可独立交付

## 背景

评测中心前端共 8 个视图 + 4 个业务组件。经审计发现 5 个 🔴 级运行时错误、4 个 🟡 级结构/一致性问题、11 个 🟢 级优化项。

核心发现：
- **5 个组件使用了但从未 import**（Select、Checkbox、EvalProgressBar），浏览器控制台报 `Unknown custom element`，对应 UI 完全不渲染
- **1 个 import 写在 `<script setup>` 之前**，Vue SFC 不处理
- **1 个模板引用了不存在的变量** `filteredItems`，移动端下拉为空
- **Overview 和 Results 两个页面 80% 内容重复**，用户分不清职责
- **状态 Badge、进度条等组件复用断裂**，同功能不同页面外观不一致

---

## 里程碑总览

| 里程碑 | 问题 | 严重度 | 工作量 |
|--------|------|--------|--------|
| M-1 | 补齐缺失的组件 import（5 个文件） | 🔴 | 15m |
| M-2 | 修复 EvalScoreBar import 位置 + 移动端 filteredItems | 🔴 | 10m |
| M-3 | 统一状态 Badge 和进度条组件复用 | 🟡 | 40m |
| M-4 | Overview / Results 页面去重整合 | 🟡 | 2h |
| M-5 | ExperimentsView 历史列表拆分 | 🟡 | 1h |
| M-6 | 清理死代码（unused imports/functions） | 🟢 | 15m |
| M-7 | EvalEvidencePanel 高级详情格式化 | 🟢 | 1h |
| M-8 | 视觉层级 + 侧栏宽度 + SSE 重连提示 | 🟢 | 30m |

---

## Task M-1: 补齐缺失的组件 import（5 个文件）

**目标**: 修复 5 个文件中使用了但未 import 的 UI 组件，消除运行时 `Unknown custom element` 错误。

**现状**（已核实源码）：

| 文件 | 缺失的 import | 使用位置 |
|------|-------------|---------|
| `EvaluationExperimentsView.vue` | Select/SelectTrigger/SelectValue/SelectContent/SelectItem | :240-260 |
| `EvaluationExperimentsView.vue` | Checkbox | :294 |
| `EvaluationExperimentsView.vue` | EvalProgressBar | :318 |
| `EvaluationRunView.vue` | Select/SelectTrigger/SelectValue/SelectContent/SelectItem | :292-301 |
| `EvaluationReviewsView.vue` | Select/SelectTrigger/SelectValue/SelectContent/SelectItem | :175-181 |

**Files:**

- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`
- Edit: `frontend/src/views/admin/EvaluationRunView.vue`
- Edit: `frontend/src/views/admin/EvaluationReviewsView.vue`

**Step 1（编辑 — ExperimentsView）**:

在 `<script setup>` 的 import 区域（第 7-8 行之间）添加：
```js
import { Checkbox } from '@/components/ui/checkbox'
import EvalProgressBar from '@/components/business/EvalProgressBar.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
```

**Step 2（编辑 — RunView）**:

在 `<script setup>` 的 import 区域（第 9-10 行之间）添加：
```js
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
```

**Step 3（编辑 — ReviewsView）**:

在 `<script setup>` 的 import 区域（第 7-8 行之间）添加：
```js
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
```

**Step 4（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 运行 `cd frontend && npx eslint src/views/admin/EvaluationExperimentsView.vue src/views/admin/EvaluationRunView.vue src/views/admin/EvaluationReviewsView.vue --no-error-on-unmatched-pattern` 确保无新增 warning

**Step 5（提交）**:

- 提交信息: `fix(frontend): add missing component imports in eval views`
- 关联: tech-audit D14 findings — Select/Checkbox/EvalProgressBar 未 import

---

## Task M-2: 修复 EvalScoreBar import 位置 + 移动端 filteredItems

**目标**: 修复 ExperimentView 中 EvalScoreBar import 位于 `<script setup>` 之外的问题；修复 RunView 中 `filteredItems` 未定义导致移动端 Case 下拉为空的问题。

**现状**（已核实源码）：

- `EvaluationExperimentView.vue:1` — `import EvalScoreBar` 写在 `<script setup>` **之前**（第 1 行），Vue SFC 编译器不会处理该 import，组件不会注册
- `EvaluationRunView.vue:297` — 模板中 `v-for="item in filteredItems"` 但 script 中只定义了 `sortedItems`，`filteredItems` 不存在

**Files:**

- Edit: `frontend/src/views/admin/EvaluationExperimentView.vue`
- Edit: `frontend/src/views/admin/EvaluationRunView.vue`

**Step 1（编辑 — ExperimentView）**:

删除第 1 行 `import EvalScoreBar from '@/components/business/EvalScoreBar.vue'`，在 `<script setup>` 内的 import 区域（第 4 行之后）添加：
```js
import EvalScoreBar from '@/components/business/EvalScoreBar.vue'
```

**Step 2（编辑 — RunView）**:

在 `sortedItems` computed 之后添加 `filteredItems` computed：
```js
const filteredItems = computed(() => {
  // 移动端下拉复用 sortedItems，不做额外筛选
  return sortedItems.value
})
```

或者，将模板中 `filteredItems` 替换为 `sortedItems`（更简洁）：
```html
<SelectItem v-for="item in sortedItems" :key="item.id" :value="String(item.id)">
```

推荐后者（直接用 sortedItems），避免引入无筛选逻辑的冗余 computed。

**Step 3（验证）**:

- 运行 `cd frontend && npm run build`
- 确认 `EvaluationExperimentView.vue` 第 1 行不再是 import 语句
- 确认 `EvaluationRunView.vue` 模板中不再引用 `filteredItems`（或已正确定义）

**Step 4（提交）**:

- 提交信息: `fix(frontend): fix EvalScoreBar import position and undefined filteredItems`
- 关联: tech-audit D14 findings

---

## Task M-3: 统一状态 Badge 和进度条组件复用

**目标**: 消除同一功能在不同页面用不同方式渲染的问题，统一使用已有封装组件。

**现状**（已核实源码）：

**状态 Badge 不一致**：
- `EvaluationOverviewView.vue:108` — 使用 `<Badge variant="default">`
- `EvaluationRunView.vue:225` — 使用 `<Badge variant="default">`
- `EvaluationReleasesView.vue:94` — 使用 `<Badge variant="default">`
- `EvaluationExperimentsView.vue:317` — 手写 `<span class="rounded-full px-2 py-0.5 text-xs">`
- `EvaluationExperimentView.vue:99` — 手写 `<span class="rounded-full px-2.5 py-1 text-sm">`
- `EvaluationResultsView.vue:183-185` — 手写 `<span class="rounded-full px-2 py-0.5 text-xs">`

**进度条不一致**：
- `EvaluationOverviewView.vue:94` — 使用 `<EvalProgressBar>` 组件
- `EvaluationResultsView.vue:150` — 使用 `<EvalProgressBar>` 组件
- `EvaluationExperimentView.vue:105` — 内联 `<div class="h-full rounded-full bg-primary">`
- `EvaluationExperimentView.vue:124` — 内联 `<div class="h-full rounded-full bg-primary">`

**Files:**

- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`
- Edit: `frontend/src/views/admin/EvaluationExperimentView.vue`
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue`

**Step 1（编辑 — ExperimentsView:317）**:

将手写 status span 替换为 `<Badge>` 组件。需要在 import 区添加：
```js
import { Badge } from '@/components/ui/badge'
```

将 `:class="['rounded-full px-2 py-0.5 text-xs', statusClass(run.status)]">{{ statusLabel(run.status) }}</span>` 替换为：
```html
<Badge :class="statusClass(run.status)">{{ statusLabel(run.status) }}</Badge>
```

对 quality_status 和实验列表的 status 做同样处理。

**Step 2（编辑 — ExperimentView:99,120）**:

将手写 status span 替换为 `<Badge>` 组件。需要在 import 区添加：
```js
import { Badge } from '@/components/ui/badge'
```

**Step 3（编辑 — ExperimentView:105,124）**:

将内联进度条替换为 `<EvalProgressBar>` 组件：
```html
<!-- 替换前 -->
<div class="mt-4 h-2 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full bg-primary transition-all duration-500" :style="{ width: `${progress}%` }" /></div>

<!-- 替换后 -->
<div class="mt-4"><EvalProgressBar :value="progress" size="md" /></div>
```

需要在 import 区添加：
```js
import EvalProgressBar from '@/components/business/EvalProgressBar.vue'
```

对第 124 行的子 Run 进度条做同样处理。

**Step 4（编辑 — ResultsView:183-185）**:

将手写 quality badge 替换为 `<Badge>` 组件。ResultsView 已 import Badge（第 11 行），但未用于 status 显示。将：
```html
<span :class="['rounded-full px-2 py-0.5 text-xs', qualityBadgeClass(run.quality_status)]">
```
替换为使用 `<Badge>` 并将 `qualityBadgeClass` 的返回值作为 class。

**Step 5（验证）**:

- 运行 `cd frontend && npm run build`
- 检查所有 eval 视图中 status 显示一致（Badge 组件 + statusClass）
- 检查所有进度条使用 EvalProgressBar 组件

**Step 6（提交）**:

- 提交信息: `fix(frontend): unify status Badge and progress bar components across eval views`
- 关联: tech-audit D16 findings

---

## Task M-4: Overview / Results 页面去重整合

**目标**: 消除 Overview 和 Results 两个页面 80% 内容重复的问题，明确各页面职责。

**现状**（已核实源码）：

两个页面重复的内容：
- 4 个统计卡（已完成/执行中/等待/失败）— Overview:28-33, Results:80-85
- `byTarget` computed — Overview:20, Results:22
- `byTargetSort` computed — Overview:21, Results:61-67
- `passRate()` 函数 — Overview:23, Results:69
- byTarget 质量看板（通过率进度条）— Overview:83-101, Results:131-157
- 失败 Run 列表 — Overview:104-113, Results:172-196

唯一差异：
- Results 多了筛选器（statusFilter + targetFilter）
- Results 多了 EvalScoreBar 显示
- Overview 多了人工 A/B 汇总

**方案**: 将 Overview 改为纯摘要 dashboard（统计卡 + 质量看板 + A/B 汇总 + 快捷入口），Results 承载全部 Run 列表和筛选功能。删除 Overview 中的失败 Run 列表（已在 Results 中）。

**Files:**

- Edit: `frontend/src/views/admin/EvaluationOverviewView.vue`
- Edit: `frontend/src/views/admin/evaluationShared.js`（提取共享逻辑）

**Step 1（提取共享逻辑到 evaluationShared.js）**:

在 `evaluationShared.js` 中添加：
```js
export function buildByTargetSort(byTarget) {
  return [...byTarget].sort((a, b) => (b.failed_count / Math.max(b.run_count, 1)) - (a.failed_count / Math.max(a.run_count, 1)))
}

export function passRate(item) {
  if (!item.run_count) return 0
  return Math.round((item.passed_count / item.run_count) * 100)
}
```

**Step 2（编辑 OverviewView）**:

- 从 evaluationShared.js import `buildByTargetSort` 和 `passRate`，删除本地定义
- 删除失败 Run 列表部分（:104-113），改为一个"查看全部结果"链接指向 Results 页面
- 保留：统计卡 + 质量看板 + 人工 A/B 汇总

**Step 3（编辑 ResultsView）**:

- 从 evaluationShared.js import `buildByTargetSort` 和 `passRate`，删除本地定义

**Step 4（验证）**:

- 运行 `cd frontend && npm run build`
- 确认 Overview 不再显示 Run 列表
- 确认 Results 页的筛选和分数显示正常

**Step 5（提交）**:

- 提交信息: `refactor(frontend): deduplicate Overview/Results pages and extract shared eval logic`
- 关联: tech-audit D1, D15 findings

---

## Task M-5: ExperimentsView 历史列表拆分

**目标**: 将 ExperimentsView 中的两个历史列表（单次评测 + 批量实验）移出，减轻页面认知负载。

**现状**（已核实源码）：

`EvaluationExperimentsView.vue` 当前包含：
- 左列：评测配置表单（:235-287）
- 右列：批量评测实验（:289-310）
- 下方卡 1：历史评测 Run 列表（:312-321）
- 下方卡 2：批量实验历史列表（:323-332）

这 4 个功能区挤在一个页面，用户打开即面对信息墙。

**方案**: 将两个历史列表移入 Results 页面（Results 已有 Run 列表，补上 Experiment 列表即可）。ExperimentsView 只保留"发起评测"功能。

**Files:**

- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue`
- Edit: `frontend/src/services/evaluationApi.js`（确认 Results 需要的 API 已有）

**Step 1（编辑 — ExperimentsView）**:

删除"历史评测"卡（:312-321）和"批量实验历史"卡（:323-332）。同时删除不再需要的 `runs`、`experiments` ref 及其在 `load()` 中的获取逻辑（只保留 releases、capabilities、benchmarks 的获取）。

删除 `import { fetchEvaluationRuns, fetchEvaluationExperiments }` 中不再需要的部分。

**Step 2（编辑 — ResultsView）**:

在"最近评测运行"卡之后，添加"批量实验历史"卡，复用 ExperimentsView 中的实验列表模板。需要：
- 添加 `experiments` ref
- 在 `load()` 中调用 `fetchEvaluationExperiments()`
- 添加实验列表的模板（从 ExperimentsView 迁移）

**Step 3（验证）**:

- 运行 `cd frontend && npm run build`
- 确认 ExperimentsView 只显示配置表单和批量实验选择
- 确认 Results 页面同时显示 Run 列表和 Experiment 列表

**Step 4（提交）**:

- 提交信息: `refactor(frontend): move eval history lists from ExperimentsView to ResultsView`
- 关联: tech-audit D15 findings

---

## Task M-6: 清理死代码（unused imports/functions）

**目标**: 删除 ESLint 报告的 11 个 unused-import/function warning。

**现状**（ESLint 核实）：

| 文件 | 未使用 |
|------|-------|
| `EvalScoreBar.vue:2` | `props` 赋值后未引用 |
| `EvaluationOverviewView.vue:9` | `runProgress`, `statusClass` |
| `EvaluationReleasesView.vue:6-7` | `fetchEvaluationBenchmarks`, `statusClass` |
| `EvaluationResultsView.vue:3` | `ArrowRight` |
| `EvaluationReviewsView.vue:13` | `Badge` |
| `EvaluationRunView.vue:5,11,72,89` | `AppCard`, `checkStatusLabel`, `deterministicSummary`, `scoreSummary` |

**Files:**

- Edit: `frontend/src/components/business/EvalScoreBar.vue`
- Edit: `frontend/src/views/admin/EvaluationOverviewView.vue`
- Edit: `frontend/src/views/admin/EvaluationReleasesView.vue`
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue`
- Edit: `frontend/src/views/admin/EvaluationReviewsView.vue`
- Edit: `frontend/src/views/admin/EvaluationRunView.vue`

**Step 1（逐文件删除未使用的 import/function）**:

- `EvalScoreBar.vue:2` — 将 `const props = defineProps(...)` 改为 `defineProps(...)`
- `EvaluationOverviewView.vue:9` — 从 destructure 中删除 `runProgress`, `statusClass`
- `EvaluationReleasesView.vue:6` — 删除 `fetchEvaluationBenchmarks` import（注意：ReleasesView 内部仍有 `benchmarks` ref 和 `benchmarkOf()` 函数，需确认 load() 是否仍需获取 benchmarks；如果 ReleasesView 的 load() 不调用 fetchEvaluationBenchmarks，则可安全删除）
- `EvaluationReleasesView.vue:7` — 从 destructure 中删除 `statusClass`
- `EvaluationResultsView.vue:3` — 删除 `ArrowRight` import
- `EvaluationReviewsView.vue:13` — 删除 `Badge` import
- `EvaluationRunView.vue:5` — 删除 `AppCard` import
- `EvaluationRunView.vue:11` — 从 destructure 中删除 `checkStatusLabel`
- `EvaluationRunView.vue:72-87` — 删除 `deterministicSummary` 函数
- `EvaluationRunView.vue:89-101` — 删除 `scoreSummary` 函数

**Step 2（验证）**:

- 运行 `cd frontend && npm run build`
- 运行 ESLint 确认 eval 文件 warning 数降为 0

**Step 3（提交）**:

- 提交信息: `refactor(frontend): remove unused imports and functions in eval views`
- 关联: tech-audit D14 findings

---

## Task M-7: EvalEvidencePanel 高级详情格式化

**目标**: 将「高级详情」中的 raw JSON.stringify 替换为结构化展示。

**现状**（已核实源码）：

`EvalEvidencePanel.vue:93-95` 三处 JSON dump：
- `evidence.case?.input_snapshot` — 候选人可见输入
- `evidence.case?.contract` — 确定性契约
- `attempt.raw_observation` — Attempt 原始观察

当前用 `<pre>{{ JSON.stringify(..., null, 2) }}</pre>` 直接渲染，用户看到大段 JSON 无法快速获取关键信息。

**方案**:
- 候选人输入：提取关键字段（如问题列表、JD 摘要、简历摘要）做标签展示；完整 JSON 折叠到 `<details>` 内并加一键复制按钮
- 确定性契约：提取 hard_assertions 数量和 rubric 键列表做摘要；完整 JSON 折叠
- Attempt 记录：保留 attempt_index + status 摘要，raw_observation 折叠

**Files:**

- Edit: `frontend/src/components/business/EvalEvidencePanel.vue`

**Step 1（编辑）**:

替换 :93-95 的 JSON dump 区域：
```html
<!-- 候选人输入摘要 -->
<div v-if="evidence">
  <div class="mb-1 text-xs font-medium">候选人可见输入</div>
  <div class="flex flex-wrap gap-1.5 mb-2">
    <span v-if="evidence.case?.input_snapshot?.question" class="rounded-md bg-muted px-2 py-1 text-xs">
      问题: {{ evidence.case.input_snapshot.question.slice(0, 60) }}...
    </span>
    <!-- 其他关键字段类似 -->
  </div>
  <details class="text-xs">
    <summary class="cursor-pointer text-muted-foreground">查看完整 JSON</summary>
    <pre class="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-2">{{ JSON.stringify(evidence.case?.input_snapshot || {}, null, 2) }}</pre>
  </details>
</div>
```

对 contract 和 attempt 做类似处理。

**Step 2（验证）**:

- 运行 `cd frontend && npm run build`
- 手动确认高级详情区域展示正常

**Step 3（提交）**:

- 提交信息: `fix(frontend): format EvalEvidencePanel advanced details with structured display`
- 关联: tech-audit D16 findings

---

## Task M-8: 视觉层级 + 侧栏宽度 + SSE 重连提示

**目标**: 改善三个小的 UX 问题。

**现状**（已核实源码）：

1. **侧栏宽度** — `EvaluationRunView.vue:305` 固定 `w-64`（256px），长 case_key 被截断
2. **SSE 重连提示** — `EvaluationRunView.vue:128` 重连时只写 `error.value`，用户可能看不到
3. **视觉层级** — 全域 130+ 处 text-xs/text-sm，关键数据无视觉权重区分

**Files:**

- Edit: `frontend/src/views/admin/EvaluationRunView.vue`

**Step 1（侧栏宽度）**:

将 `w-64` 改为 `w-72` 或 `w-80`，并在 case_key 的 `<span>` 上添加 `title` 属性：
```html
<span class="font-medium" :title="item.case_key">{{ item.case_key }}</span>
```

**Step 2（SSE 重连提示）**:

在 header 进度条下方添加 sticky 重连状态条：
```html
<div v-if="error && !terminal" class="mx-auto max-w-[1600px] px-4 py-1">
  <div class="rounded-md bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700 flex items-center gap-2">
    <RefreshCw class="size-3 animate-spin" />{{ error }}
  </div>
</div>
```

**Step 3（验证）**:

- 运行 `cd frontend && npm run build`

**Step 4（提交）**:

- 提交信息: `fix(frontend): widen eval case sidebar, add SSE reconnect indicator`
- 关联: tech-audit D15 findings

---

## 验收标准

1. **零 🔴**: 所有 eval 视图中 Select/Checkbox/EvalProgressBar/EvalScoreBar 正常渲染
2. **零 ESLint warning**: `npx eslint src/views/admin/Evaluation*.vue src/components/business/Eval*.vue` 输出 0 warning
3. **构建通过**: `cd frontend && npm run build`
4. **组件复用统一**: 所有状态显示用 `<Badge>`，所有进度条用 `<EvalProgressBar>`
5. **Overview/Results 职责清晰**: Overview 为摘要 dashboard，Results 为 Run/Experiment 列表
6. **ExperimentsView 职责单一**: 只包含"发起评测"功能，历史列表在 Results
7. **无死代码**: 所有 eval 文件的 unused import = 0

---

## 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 补 import 后 Select 组件样式与预期不符 | 低 | 低 | shadcn-vue Select 组件已全局注册，补 import 即可正常渲染 |
| Overview 删除 Run 列表后用户找不到 | 低 | 低 | Results 页面已有完整 Run 列表，导航中已有入口 |
| ExperimentsView 删除历史后用户困惑 | 低 | 低 | 在 ExperimentsView 底部添加"查看历史结果"链接指向 Results |
| 共享逻辑提取后 breaking change | 低 | 中 | 函数签名不变，只是位置变化，构建测试验证 |

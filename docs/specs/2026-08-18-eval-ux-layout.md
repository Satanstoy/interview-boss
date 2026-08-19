# Spec: 评测工作台 UX 升级

> 位置: `frontend/src/views/admin/Evaluation*.vue` + `frontend/src/views/admin/evaluationShared.js`
> 类型: 前端 UX spec（设计驱动）
> 日期: 2026-08-18
> 状态: 待实施
> 方法: TDD（先写失败测试）→ 最小实现 → 验证 → 提交

## 背景

评测中心现有 10 个 Vue 页面，覆盖「版本发布 → Benchmark → 测评实验 → 评测结果 → 人工 A/B」五步流程。经 UX 盘点，发现以下核心问题：

| 页面 | 现状问题 | 违背的最佳实践 |
|------|---------|---------------|
| Run 详情 (`EvaluationRunView.vue`) | 逐 Case 表格 + 证据抽屉整体下推；看下一个 Case 要滚回表格再点 | 无 navigator、无键盘遍历、无进度显示、无 Case N/M |
| Experiment 详情 (`EvaluationExperimentView.vue`) | 汇总卡 + 扁平子 Run 列表，没有分数横条/质量占比 | 无 result dashboard 分层 |
| 评测结果 (`EvaluationResultsView.vue`) | 平铺 Run 列表，无排序、无分数条 | 无 leaderboard / 无优先级 |
| 人工 A/B (`EvaluationReviewsView.vue`) | 有左右两栏但靠滚动对齐，无键盘、无进度 | 非 forced compare、无键盘遍历 |
| 各页面 | 徽章语义颜色弱（只有绿/红/黄文本），失败原因藏在抽屉里 | 无 assessment 语义着色 |

**最佳实践来源**：
- Hamel Husain / thingsithinkithink LLM Evals Course Lesson 7 — Interfaces for Human Review（issue-prioritization、navigator、progress、forced side-by-side）
- MLflow Assessment UI — 评估结果语义着色 + sampled prompts
- Langfuse v4 / Arize Phoenix — 分数/维度直接在 trace 面板标注

## 实施顺序

M-UX-1（评测工作台布局） → M-UX-2（实验/结果可视化） → M-UX-3（人工 A/B 增强）。每个里程碑独立可交付、可验收。

---

## Task M-UX-1: Run 详情评测工作台布局

**目标**：将 `EvaluationRunView.vue` 从「表格 + 抽屉」模式重构为「左侧 Case 导航 + 右侧证据面板」全屏工作台，对齐 ChatView 式工作台模式。

**Files:**

- Create: `frontend/src/components/business/EvalCaseNavigator.vue`
- Create: `frontend/src/components/business/EvalEvidencePanel.vue`
- Edit: `frontend/src/views/admin/EvaluationRunView.vue`
- Edit: `frontend/src/views/admin/evaluationShared.js`
- Create: `frontend/tests/eval-workspace.spec.js`（Playwright 冒烟测试）

**设计原则**（来源 Lesson 7）：

- **Navigator 模式**：左侧窄栏列 Case 导航条（case_key + 状态圆点 + 分数），右侧主面板一次只展示一个 Case 的完整证据
- **Issue-prioritization**：默认排序把失败 Case（`status=failed`）置顶，其次是待判定（`status=completed` 但 `hard_gate_status=failed`），最后是通过的 Case
- **Progress**：顶部固定条显示「第 N/M 个 · 通过 X · 失败 Y · Judge 未完成 Z」
- **Keyboard**：J/K 切换上下 Case，Escape 关闭证据面板
- **Assessment 语义着色**：状态圆点颜色统一 — 绿色（通过）、红色（失败）、黄色（进行中）、灰色（待处理）

**Step 1（RED）— 测试**：

- 测试导航器渲染：给定 N 个 items 的 run 数据，左侧导航栏渲染 N 条导航条
- 测试排序逻辑：failed 项排在前面
- 测试键盘 J/K：按下 J 切换到下一个 Case，按下 K 切换到上一个 Case
- 测试 Progress 计算：给定 completed/failed/running 统计，顶部显示正确的 N/M 和分类计数

**Step 2 — 实现 EvalCaseNavigator.vue**：

- Props: `items: Array`, `activeId: number`, `sortMode: 'priority' | 'original'`
- 渲染：每条 item 是一个 button，显示 `case_key`、状态圆点（badge dot）、分数（`score?.toFixed(3)`）
- 排序：sortMode='priority' 时 failed → failed_contract → completed → 其他
- 点击事件：emit `select` + item.id

**Step 3 — 实现 EvalEvidencePanel.vue**：

- Props: `item: Object`, `loading: boolean`, `error: string`
- 用 `ScrollArea` 包裹整个证据区域
- 内容布局：输入快照（左）+ 确定性契约（右）→ Agent 输出/轨迹 → Hard Gate 证据 → Judge 结果 → Attempt 记录 → Artifact 索引
- 数据获取由父组件 `EvaluationRunView` 调用 `fetchEvaluationItem`，通过 props 传入

**Step 4 — 重构 EvaluationRunView.vue**：

- 保留顶部进度条 + 阶段指示器 + 版本绑定信息（不变）
- 将逐 Case 表格区域替换为：左侧 `EvalCaseNavigator`（固定宽度 w-64）+ 右侧 `EvalEvidencePanel`（flex-1）
- 移除底部独立的「Case 证据」卡片（已被 EvidencePanel 取代）
- 添加键盘监听：J/K 切换 activeCaseIndex，Escape 清空选中
- 页面加载后自动选中第一个失败 Case（若无则第一个 Case）

**Step 5 — Playwright 冒烟测试**：

- mock API 返回含 5 个 items 的 run 数据
- 断言左侧导航渲染 5 条
- 断言失败 item 排在前面
- 断言点击后右侧显示证据面板

---

## Task M-UX-2: 实验/结果可视化增强

**目标**：Experiment 详情页增加子 Run 分数横条；Results 页改为 leaderboard 排序视图。

**Files:**

- Create: `frontend/src/components/business/EvalScoreBar.vue`（三色段分数横条组件）
- Edit: `frontend/src/views/admin/EvaluationExperimentView.vue`
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue`

**EvalScoreBar 组件**：

- Props: `deterministic: number|null`, `judge: number|null`, `final: number|null`, `height: string (default 'h-2')`
- 渲染：三层叠加的横条 — 底层灰色（整体宽度）→ 中间蓝色段（规则分占比）→ 顶层绿色段（Judge 分占比）
- 当 final=null 时显示「—」文本替代横条

**Step 1（RED）— 测试**：

- EvalScoreBar：给定 deterministic=0.7, judge=0.8, final=0.75 → 渲染三色段
- EvalScoreBar：给定 null 值 → 显示「—」
- ExperimentView：子 Run 列表渲染 EvalScoreBar
- ResultsView：Run 列表按 final_mean 降序排列

**Step 2 — 实现 EvalScoreBar.vue**：

- 三个 div 叠加（relative + absolute），宽度百分比由 deterministic/judge 决定
- 背景色：`bg-muted`（底）、`bg-blue-500`（规则）、`bg-emerald-500`（Judge）

**Step 3 — 改造 EvaluationExperimentView.vue**：

- 在子 Run 每行增加 EvalScoreBar（从 `run.score` 读取）
- 子 Run 行增加质量徽章（`Badge` 组件）：通过=绿、失败=红、待判定=黄

**Step 4 — 改造 EvaluationResultsView.vue**：

- Run 列表改为按 `score.final_mean` 降序排列（默认）
- 每行增加 EvalScoreBar + 质量徽章
- 顶部增加排序切换：按分数 / 按时间

---

## Task M-UX-3: 人工 A/B 审查增强

**目标**：将 `EvaluationReviewsView.vue` 从「表单式」改为「强制双栏固定比较 + 键盘快捷键 + 进度」工作台。

**Files:**

- Edit: `frontend/src/views/admin/EvaluationReviewsView.vue`
- Edit: `frontend/src/views/admin/evaluationShared.js`（新增 keyboard 常量）

**设计原则**（来源 Lesson 7 forced side-by-side）：

- **Forced compare**：A/B 双栏固定在视口内（各自独立滚动），不依赖用户手动对齐
- **Navigator + Progress**：顶部进度条「第 N/M 个 Case · 已审 X 个」
- **Keyboard**：1=A 更好、2=B 更好、3=平局、4=都失败、← → 切换 Case

**Step 1（RED）— 测试**：

- 测试双栏渲染：选中一个 Case 后，A 栏和 B 栏同时显示各自 turns
- 测试键盘 1/2/3/4：按下数字键选择判断
- 测试进度：给定 reviews 列表和 itemKeys，计算已审/总数
- 测试 Case 切换：← → 键切换到上/下一个 Case

**Step 2 — 重构模板**：

- 顶部区域：排序步骤指示器（保留现有 4 步流程）+ 进度条（N/M）
- 主体区域：左右固定双栏（`grid grid-cols-2 gap-4`），每栏内 ScrollArea 包裹 turns 列表
- 底部区域：判断选择按钮组（A 更好 / B 更好 / 平局 / 都失败）+ 备注输入 + 保存
- Case 切换：用按钮组或下拉选择 Case Key（保留现有 itemKeys 计算）

**Step 3 — 添加键盘快捷键**：

- `onMounted` 注册 keydown 监听
- 数字键 1/2/3/4 → 选择判断
- Left/Right → 切换 Case
- Enter → 保存当前判断
- `onUnmounted` 移除监听

---

## Task M-UX-4: 共享工具函数与 CLAUDE.md 更新

**目标**：统一 assessment 语义着色逻辑、更新 CLAUDE.md。

**Files:**

- Edit: `frontend/src/views/admin/evaluationShared.js`
- Edit: `frontend/CLAUDE.md`
- Edit: `frontend/src/views/CLAUDE.md`

**Step 1 — evaluationShared.js 新增**：

- `scoreBarColorClass(score)` — 根据分数返回颜色 class（0.8+ 绿、0.5-0.8 黄、<0.5 红）
- `casePrioritySort(items)` — 将 items 按 failed > failed_contract > completed > 其他排序
- `CASE_KEYBOARD_SHORTCUTS` — 键盘快捷键映射常量

**Step 2 — 更新 CLAUDE.md**：

- 在 frontend/CLAUDE.md 的「代码路由表」中更新评测中心相关条目
- 在 frontend/src/views/CLAUDE.md 中增加新组件说明

---

## 验收标准

1. M-UX-1：Run 详情页左侧显示 Case 导航栏（失败优先排序），右侧显示证据面板，J/K 可切换
2. M-UX-2：Experiment 详情页每个子 Run 显示分数横条；Results 页支持按分数排序
3. M-UX-3：人工 A/B 双栏固定比较，数字键快捷判断，显示已审进度
4. 所有页面构建通过（`npm run build`），无 ESLint 错误
5. Playwright 冒烟测试通过

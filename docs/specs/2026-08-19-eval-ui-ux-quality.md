# Spec: 评测中心 UI/UX 质量提升 — 内联样式清理与可访问性统一

> 位置: `frontend/src/views/admin/Evaluation*.vue` + `frontend/src/views/admin/evaluationShared.js`
> 类型: 前端 UI/UX 质量 spec（代码质量驱动）
> 日期: 2026-08-19
> 状态: 待实施
> 审计依据: UI/UX 代码审查（2026-08-19）
> 方法: 最小变更 → 验证 → 提交

## 背景

评测中心现有 6 个 Vue 页面，经 UI/UX 代码审查发现以下质量问题：

| 问题 | 位置 | 现状 | 影响 |
|------|------|------|------|
| 内联样式 | 5 个视图文件 | 使用 style="..." 进行动态样式绑定 | 违反样式分离原则，维护困难 |
| 可访问性不一致 | 多个视图文件 | 部分视图有 aria 属性，部分没有 | 可访问性标准不统一 |
| 组件使用不一致 | 多个视图文件 | 有些视图使用更多 shadcn 组件 | UI 一致性受损 |

**根本原因**: 开发过程中样式和可访问性规范未统一执行。

---

## 问题清单与改进方案

### 问题 1 — 内联样式问题 🟡

**现状**（已核实源码）：
- EvaluationOverviewView.vue: style="{ width: passRate(item) + '%' }"
- EvaluationResultsView.vue: style="{ width: passRate(item) + '%' }"
- EvaluationExperimentsView.vue: style="{ width: runProgress(run) + '%' }"
- EvaluationReviewsView.vue: style="height: calc(100vh - 340px); min-height: 400px;"
- EvaluationRunView.vue: style="{ width: progress + '%' }"

**方案**: 将内联样式转换为 Tailwind CSS 类或 CSS 变量。

- **Step 1**: 创建可复用的进度条组件 EvalProgressBar.vue
- **Step 2**: 将动态宽度样式转换为 Tailwind 的 w-[...%] 或 CSS 变量
- **Step 3**: 将固定高度样式转换为 Tailwind 的 h-[calc(100vh-340px)] min-h-[400px]

**风险**: 低。样式转换不影响功能。

---

### 问题 2 — 可访问性不一致 🟡

**现状**（已核实）：
- EvaluationExperimentsView.vue: 2 个 aria 属性，2 个 role 属性
- EvaluationReviewsView.vue: 3 个 aria 属性，1 个 role 属性
- EvaluationRunView.vue: 1 个 aria 属性
- 其他视图: 无 aria/role 属性

**方案**: 统一添加必要的可访问性属性。

- **Step 1**: 为所有交互元素添加 aria-label
- **Step 2**: 为动态内容区域添加 aria-live
- **Step 3**: 为状态指示器添加适当的 role 属性

**风险**: 低。添加可访问性属性不影响视觉呈现。

---

### 问题 3 — 组件使用不一致 🟢

**现状**（已核实）：
- EvaluationReviewsView.vue: 使用 3 个 shadcn 组件
- EvaluationExperimentsView.vue: 使用 2 个 shadcn 组件
- 其他视图: 使用 1 个或更少 shadcn 组件

**方案**: 统一使用 shadcn 组件替代自定义样式。

- **Step 1**: 使用 Badge 组件替代自定义状态标签
- **Step 2**: 使用 Progress 组件替代自定义进度条
- **Step 3**: 使用 Card 组件统一内容容器

**风险**: 低。组件替换保持功能不变。

---

## 实施顺序

1. **M-1**: 创建可复用的进度条组件（🟡 问题，尽快修复）
2. **M-2**: 清理内联样式（🟡 问题，尽快修复）
3. **M-3**: 统一可访问性属性（🟡 问题，尽快修复）
4. **M-4**: 统一组件使用（🟢 问题，计划修复）

每个里程碑独立可交付、可验收。

---

## Task M-1: 创建可复用的进度条组件

**目标**: 创建统一的进度条组件，替代内联样式实现。

**Files:**

- Create: frontend/src/components/business/EvalProgressBar.vue

**Step 1（创建组件）**:

创建 EvalProgressBar.vue 组件，支持以下功能：
- 动态宽度绑定（0-100%）
- 颜色状态（成功/警告/错误）
- 可访问性属性（role="progressbar"，aria-valuenow，aria-valuemin，aria-valuemax）

**Step 2（验证）**:

- 运行 cd frontend && npm run build 确保构建通过

**Step 3（提交）**:

- 提交信息: feat(frontend): add reusable EvalProgressBar component
- 关联问题: 内联样式清理

---

## Task M-2: 清理内联样式

**目标**: 将所有内联样式转换为 Tailwind CSS 类或组件属性。

**Files:**

- Edit: frontend/src/views/admin/EvaluationOverviewView.vue
- Edit: frontend/src/views/admin/EvaluationResultsView.vue
- Edit: frontend/src/views/admin/EvaluationExperimentsView.vue
- Edit: frontend/src/views/admin/EvaluationReviewsView.vue
- Edit: frontend/src/views/admin/EvaluationRunView.vue

**Step 1（编辑）**:

将每个视图中的内联样式替换为：
1. 动态宽度: 使用 EvalProgressBar 组件或 :style="{ width: ... + '%' }"
2. 固定高度: 使用 Tailwind 类 h-[calc(100vh-340px)] min-h-[400px]

**Step 2（验证）**:

- 运行 cd frontend && npm run build 确保构建通过
- 手动验证进度条显示正常

**Step 3（提交）**:

- 提交信息: refactor(frontend): replace inline styles with Tailwind classes
- 关联问题: 内联样式清理

---

## Task M-3: 统一可访问性属性

**目标**: 为所有视图添加统一的可访问性属性。

**Files:**

- Edit: frontend/src/views/admin/EvaluationOverviewView.vue
- Edit: frontend/src/views/admin/EvaluationResultsView.vue
- Edit: frontend/src/views/admin/EvaluationExperimentsView.vue
- Edit: frontend/src/views/admin/EvaluationReleasesView.vue
- Edit: frontend/src/views/admin/EvaluationReviewsView.vue
- Edit: frontend/src/views/admin/EvaluationRunView.vue

**Step 1（编辑）**:

为每个视图添加：
1. 页面标题区域: aria-labelledby
2. 动态内容: aria-live="polite"
3. 状态指示器: role="status" 或 role="alert"
4. 交互按钮: aria-label

**Step 2（验证）**:

- 运行 cd frontend && npm run build 确保构建通过
- 使用屏幕阅读器测试可访问性

**Step 3（提交）**:

- 提交信息: fix(frontend): add consistent accessibility attributes to eval views
- 关联问题: 可访问性不一致

---

## Task M-4: 统一组件使用

**目标**: 统一使用 shadcn 组件替代自定义样式。

**Files:**

- Edit: frontend/src/views/admin/Evaluation*.vue

**Step 1（编辑）**:

1. 使用 Badge 组件替代自定义状态标签
2. 使用 Progress 组件替代自定义进度条（如适用）
3. 使用 Card 组件统一内容容器

**Step 2（验证）**:

- 运行 cd frontend && npm run build 确保构建通过
- 手动验证 UI 一致性

**Step 3（提交）**:

- 提交信息: refactor(frontend): standardize shadcn component usage in eval views
- 关联问题: 组件使用不一致

---

## 验收标准

1. 无内联样式: 所有 style="..." 被替换为 Tailwind 类或组件属性
2. 可访问性统一: 所有视图有必要的 aria-* 和 role 属性
3. 组件一致性: 统一使用 shadcn 组件
4. 构建通过: cd frontend && npm run build 成功
5. 功能正常: 所有评测中心功能正常工作

---

## 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 样式转换导致视觉差异 | 低 | 中 | 仔细对比转换前后的视觉效果 |
| 可访问性属性添加影响交互 | 低 | 低 | 测试键盘导航和屏幕阅读器 |
| 组件替换导致功能异常 | 低 | 中 | 逐步替换并测试每个组件 |

---

## 后续建议

1. **建立 UI/UX 规范**: 创建评测中心 UI/UX 规范文档
2. **代码审查清单**: 将内联样式和可访问性检查加入代码审查清单
3. **自动化检查**: 添加 ESLint 规则检查内联样式和可访问性
4. **用户测试**: 收集用户对评测中心 UI 的反馈

---

## 技术细节

### 内联样式转换示例

**Before:**
<div style="{ width: passRate(item) + '%' }"></div>

**After (方案1 - Tailwind):**
<div :class="['w-[' + passRate(item) + '%]']"></div>

**After (方案2 - 组件):**
<EvalProgressBar :value="passRate(item)" />

### 可访问性属性示例

**Before:**
<div>{{ status }}</div>

**After:**
<div role="status" aria-live="polite">{{ status }}</div>

# Spec: 评测中心 UI 组件统一 — shadcn 组件标准化

> 位置: `frontend/src/views/admin/Evaluation*.vue`
> 类型: 前端 UI 组件统一 spec（一致性驱动）
> 日期: 2026-08-19
> 状态: 待实施
> 审计依据: UI 组件使用审计（2026-08-19）
> 方法: 最小变更 → 验证 → 提交

## 背景

评测中心现有 6 个 Vue 页面，经 UI 组件使用审计发现以下不一致问题：

| 问题 | 位置 | 现状 | 影响 |
|------|------|------|------|
| 混合使用原生按钮和 shadcn Button | 5 个视图文件 | 原生按钮 11 个，shadcn Button 18 个 | 按钮样式不一致 |
| 使用原生 select 而非 shadcn Select | 3 个视图文件 | 原生 select 7 个 | 选择框样式不一致 |
| 使用原生 input 而非 shadcn Input | 1 个视图文件 | 原生 input 3 个 | 输入框样式不一致 |
| 使用原生 checkbox 而非 shadcn Checkbox | 1 个视图文件 | 原生 checkbox 1 个 | 复选框样式不一致 |
| 使用自定义卡片样式而非 shadcn Card | 2 个视图文件 | 自定义卡片样式 2 个 | 卡片样式不一致 |

**根本原因**: 开发过程中未统一使用 shadcn 组件，导致 UI 一致性受损。

---

## 问题清单与改进方案

### 问题 1 — 混合使用原生按钮和 shadcn Button 🟡

**现状**（已核实源码）：
- EvaluationOverviewView.vue: 原生按钮 1 个，shadcn Button 3 个
- EvaluationResultsView.vue: 原生按钮 3 个，shadcn Button 3 个
- EvaluationExperimentsView.vue: 原生按钮 6 个，shadcn Button 5 个
- EvaluationReviewsView.vue: 原生按钮 1 个，shadcn Button 4 个

**方案**: 将所有原生按钮替换为 shadcn Button 组件。

- **Step 1**: 导入 Button 组件
- **Step 2**: 将 `<button>` 替换为 `<Button>`
- **Step 3**: 将原生 class 转换为 Button 的 variant 和 size 属性

**风险**: 低。按钮功能不变，仅样式统一。

---

### 问题 2 — 使用原生 select 而非 shadcn Select 🟡

**现状**（已核实源码）：
- EvaluationExperimentsView.vue: 原生 select 2 个
- EvaluationReviewsView.vue: 原生 select 4 个
- EvaluationRunView.vue: 原生 select 1 个

**方案**: 将所有原生 select 替换为 shadcn Select 组件。

- **Step 1**: 导入 Select 相关组件（Select, SelectTrigger, SelectContent, SelectItem, SelectValue）
- **Step 2**: 将 `<select>` 替换为 shadcn Select 结构
- **Step 3**: 保持 v-model 绑定不变

**风险**: 低。选择框功能不变，仅样式统一。

---

### 问题 3 — 使用原生 input 而非 shadcn Input 🟡

**现状**（已核实源码）：
- EvaluationExperimentsView.vue: 原生 input 3 个（2 个 number，1 个 checkbox）

**方案**: 将原生 input 替换为 shadcn Input 或 Checkbox 组件。

- **Step 1**: 导入 Input 和 Checkbox 组件
- **Step 2**: 将 `<input type="number">` 替换为 `<Input type="number">`
- **Step 3**: 将 `<input type="checkbox">` 替换为 `<Checkbox>`

**风险**: 低。输入框功能不变，仅样式统一。

---

### 问题 4 — 使用自定义卡片样式而非 shadcn Card 🟢

**现状**（已核实源码）：
- EvaluationOverviewView.vue: 自定义卡片样式 1 个
- EvaluationExperimentsView.vue: 自定义卡片样式 1 个

**方案**: 将自定义卡片样式替换为 shadcn Card 组件。

- **Step 1**: 导入 Card 相关组件（Card, CardHeader, CardContent, CardTitle, CardDescription）
- **Step 2**: 将自定义 div 替换为 Card 结构
- **Step 3**: 保持内容布局不变

**风险**: 低。卡片功能不变，仅样式统一。

---

## 实施顺序

1. **M-1**: 统一按钮组件（🟡 问题，尽快修复）
2. **M-2**: 统一选择框组件（🟡 问题，尽快修复）
3. **M-3**: 统一输入框组件（🟡 问题，尽快修复）
4. **M-4**: 统一卡片组件（🟢 问题，计划修复）

每个里程碑独立可交付、可验收。

---

## Task M-1: 统一按钮组件

**目标**: 将所有原生按钮替换为 shadcn Button 组件。

**Files:**

- Edit: `frontend/src/views/admin/EvaluationOverviewView.vue`
- Edit: `frontend/src/views/admin/EvaluationResultsView.vue`
- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`
- Edit: `frontend/src/views/admin/EvaluationReviewsView.vue`

**Step 1（导入组件）**:

确保每个文件都导入了 Button 组件：
\`\`\`javascript
import { Button } from '@/components/ui/button'
\`\`\`

**Step 2（替换按钮）**:

将原生按钮替换为 shadcn Button：
- `<button>` → `<Button>`
- `</button>` → `</Button>`
- 根据功能添加 variant 属性（default, destructive, outline, secondary, ghost, link）
- 根据大小添加 size 属性（default, sm, lg, icon）

**Step 3（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 手动验证按钮样式和功能正常

**Step 4（提交）**:

- 提交信息: `refactor(frontend): standardize Button components in eval views`

---

## Task M-2: 统一选择框组件

**目标**: 将所有原生 select 替换为 shadcn Select 组件。

**Files:**

- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`
- Edit: `frontend/src/views/admin/EvaluationReviewsView.vue`
- Edit: `frontend/src/views/admin/EvaluationRunView.vue`

**Step 1（导入组件）**:

导入 Select 相关组件：
\`\`\`javascript
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
\`\`\`

**Step 2（替换选择框）**:

将原生 select 替换为 shadcn Select 结构：
\`\`\`vue
<!-- Before -->
<select v-model="form.target" class="...">
  <option value="">请选择</option>
  <option v-for="item in items" :key="item.id" :value="item.id">
    {{ item.name }}
  </option>
</select>

<!-- After -->
<Select v-model="form.target">
  <SelectTrigger class="...">
    <SelectValue placeholder="请选择" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem v-for="item in items" :key="item.id" :value="item.id">
      {{ item.name }}
    </SelectItem>
  </SelectContent>
</Select>
\`\`\`

**Step 3（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 手动验证选择框功能正常

**Step 4（提交）**:

- 提交信息: `refactor(frontend): standardize Select components in eval views`

---

## Task M-3: 统一输入框组件

**目标**: 将原生 input 替换为 shadcn Input 或 Checkbox 组件。

**Files:**

- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`

**Step 1（导入组件）**:

导入 Input 和 Checkbox 组件：
\`\`\`javascript
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
\`\`\`

**Step 2（替换输入框）**:

将原生 input 替换为 shadcn 组件：
- `<input type="number">` → `<Input type="number">`
- `<input type="checkbox">` → `<Checkbox>`

**Step 3（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 手动验证输入框功能正常

**Step 4（提交）**:

- 提交信息: `refactor(frontend): standardize Input/Checkbox components in eval views`

---

## Task M-4: 统一卡片组件

**目标**: 将自定义卡片样式替换为 shadcn Card 组件。

**Files:**

- Edit: `frontend/src/views/admin/EvaluationOverviewView.vue`
- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`

**Step 1（导入组件）**:

导入 Card 相关组件：
\`\`\`javascript
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
\`\`\`

**Step 2（替换卡片）**:

将自定义 div 替换为 Card 结构：
\`\`\`vue
<!-- Before -->
<div class="rounded-xl border border-border bg-card shadow-sm">
  <div class="p-4">
    <h3 class="font-medium">标题</h3>
    <p class="text-sm text-muted-foreground">描述</p>
  </div>
  <div class="p-4">
    内容
  </div>
</div>

<!-- After -->
<Card>
  <CardHeader>
    <CardTitle>标题</CardTitle>
    <CardDescription>描述</CardDescription>
  </CardHeader>
  <CardContent>
    内容
  </CardContent>
</Card>
\`\`\`

**Step 3（验证）**:

- 运行 `cd frontend && npm run build` 确保构建通过
- 手动验证卡片样式和功能正常

**Step 4（提交）**:

- 提交信息: `refactor(frontend): standardize Card components in eval views`

---

## 验收标准

1. 无原生按钮: 所有 `<button>` 被替换为 `<Button>`
2. 无原生选择框: 所有 `<select>` 被替换为 shadcn Select
3. 无原生输入框: 所有 `<input>` 被替换为 shadcn Input 或 Checkbox
4. 无自定义卡片: 所有自定义卡片样式被替换为 shadcn Card
5. 构建通过: `cd frontend && npm run build` 成功
6. 功能正常: 所有评测中心功能正常工作

---

## 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 组件替换导致功能异常 | 低 | 中 | 逐步替换并测试每个组件 |
| 样式差异导致视觉不一致 | 低 | 中 | 仔细对比替换前后的视觉效果 |
| 事件绑定丢失 | 低 | 中 | 确保所有事件正确绑定 |

---

## 后续建议

1. **建立组件使用规范**: 创建评测中心 UI 组件使用规范文档
2. **代码审查清单**: 将 shadcn 组件使用检查加入代码审查清单
3. **自动化检查**: 添加 ESLint 规则检查原生 HTML 元素使用
4. **用户测试**: 收集用户对评测中心 UI 的反馈

---

## 技术细节

### 按钮替换示例

**Before:**
\`\`\`vue
<button type="button" class="rounded-md px-3 py-1.5 text-xs transition-colors hover:bg-muted" @click="handleClick">
  点击
</button>
\`\`\`

**After:**
\`\`\`vue
<Button variant="ghost" size="sm" @click="handleClick">
  点击
</Button>
\`\`\`

### 选择框替换示例

**Before:**
\`\`\`vue
<select v-model="form.target" class="mt-1.5 h-10 w-full rounded-md border border-input bg-background px-3 py-2">
  <option value="">请选择目标</option>
  <option v-for="target in targets" :key="target" :value="target">
    {{ target }}
  </option>
</select>
\`\`\`

**After:**
\`\`\`vue
<Select v-model="form.target">
  <SelectTrigger class="mt-1.5">
    <SelectValue placeholder="请选择目标" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem v-for="target in targets" :key="target" :value="target">
      {{ target }}
    </SelectItem>
  </SelectContent>
</Select>
\`\`\`

### 卡片替换示例

**Before:**
\`\`\`vue
<div class="rounded-xl border border-border bg-card shadow-sm">
  <div class="p-4">
    <h3 class="font-medium">标题</h3>
  </div>
  <div class="p-4">
    内容
  </div>
</div>
\`\`\`

**After:**
\`\`\`vue
<Card>
  <CardHeader>
    <CardTitle>标题</CardTitle>
  </CardHeader>
  <CardContent>
    内容
  </CardContent>
</Card>
\`\`\`

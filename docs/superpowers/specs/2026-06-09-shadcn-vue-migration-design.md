# shadcn-vue 全盘迁移设计文档

> 日期：2026-06-09
> 状态：已批准
> 范围：frontend/ 全部组件，common 优先

## 背景

项目已初始化 shadcn-vue（v2.7.3），安装了 27 个 UI 组件组，但实际使用率极低：
- 16/17 个 common 组件未使用 shadcn（仅 TabBar.vue 用了 Tabs）
- 大部分 business 组件使用手写 CSS 类（`btn-primary`、`card-smooth` 等）
- 风格不统一，维护成本高

## 决策

- **跳过 init 命令**：现有 `components.json` 配置足够（style: reka-vega, font: figtree）
- **迁移范围**：全部组件（common + business），common 优先
- **迁移策略**：直接替换，删掉自定义组件，改用 shadcn UI
- **CSS 处理**：删除 global.css 中的 `btn-primary`、`btn-secondary`、`btn-ghost`、`badge`、`card-smooth`，全部用 shadcn 组件替代

## 迁移映射表

| 自定义组件/类 | → shadcn 目标 | 需新装 | 说明 |
|---|---|---|---|
| `btn-primary` CSS 类 | `<Button variant="default">` | 否 | 已有 Button.vue |
| `btn-secondary` CSS 类 | `<Button variant="outline">` | 否 | 已有 Button.vue |
| `btn-ghost` CSS 类 | `<Button variant="ghost">` | 否 | 已有 Button.vue |
| `badge` CSS 类 | `<Badge>` | 否 | 已有 Badge.vue |
| `card-smooth` CSS 类 | `<Card>` | 否 | 已有 Card.vue |
| `AppDialog.vue` | shadcn Dialog | 否 | 已有完整 Dialog 组件 |
| `BaseModal.vue` | shadcn Dialog | 否 | 与 AppDialog 功能重叠，删除 |
| `ConfirmDialog.vue` | shadcn AlertDialog | **是** | 需 `npx shadcn-vue add alert-dialog` |
| `RoundedSelect.vue` | shadcn Select | 否 | 已有 Select.vue，直接删除 |
| `AppTable.vue` | shadcn Table | 否 | 已有 Table.vue |
| `DataTable.vue` | shadcn Table + TanStack Table | 否 | TanStack 逻辑保留 |
| `BatchActionPanel.vue` | Card + Button | 否 | 组合使用 |
| `AppSearchForm.vue` | Input + Button | 否 | 已有 Input.vue |
| `AppLoading.vue` | Skeleton | 否 | 已有 Skeleton.vue |
| `AsyncLoading.vue` | Skeleton | 否 | 同上 |
| `AppEmpty.vue` | 自定义组合 | 否 | 保留，内部微调 |
| `AppPageHeader.vue` | 布局组合 | 否 | 保留，内部微调 |
| `PaginationBar.vue` | Button 组合 | 否 | shadcn 无分页组件 |
| `InlineEdit.vue` | Input inline | 否 | 已有 Input.vue |
| `AppCard.vue` | Card | 否 | 已有 Card.vue |

## 执行计划

### 第 0 步 — 前置准备
- `cd frontend && npx shadcn-vue add alert-dialog`
- 备份 `src/assets/styles/global.css`
- 确认构建通过：`npm run build`

### 第 1 批 — CSS 原语清理 + Button/Card/Badge 替换
- 从 `global.css` 删除 `btn-primary`、`btn-secondary`、`btn-ghost`、`badge`、`card-smooth` 类
- 全项目搜索这些类的使用，替换为 shadcn 组件
- 涉及文件预估：约 15-20 个文件

### 第 2 批 — Dialog/Modal 类
- `AppDialog.vue` → 改用 shadcn Dialog，保持 props 接口（open, title, description, size）
- `BaseModal.vue` → 删除，引用处改用 Dialog
- `ConfirmDialog.vue` → 改用 AlertDialog，保持 `useConfirm()` 接口不变

### 第 3 批 — 表单控件类
- `RoundedSelect.vue` → 删除，引用改为 shadcn Select
- `AppSearchForm.vue` → 内部改用 Input + Button
- `InlineEdit.vue` → 内部改用 Input

### 第 4 批 — 数据展示类
- `AppTable.vue` → 内部改用 shadcn Table
- `DataTable.vue` → 内部改用 shadcn Table
- `PaginationBar.vue` → 内部改用 Button

### 第 5 批 — 状态/布局类
- `AppLoading.vue` / `AsyncLoading.vue` → Skeleton
- `AppCard.vue` → shadcn Card
- `BatchActionPanel.vue` → Card + Button
- `AppEmpty.vue` / `AppPageHeader.vue` → 保留，微调

### 第 6 批 — 业务组件逐个迁移
- 逐个处理 `business/` 下的组件
- 替换手写样式为 shadcn 组件

每批完成后 `npm run build` 验证。

## 风险控制

- **构建验证**：每批 `npm run build`
- **视觉回归**：人工检查关键页面
- **API 兼容**：被删除组件全局搜索引用逐一替换；ConfirmDialog 的 `useConfirm()` 接口不变
- **回滚**：每批单独 commit，可 `git revert`
- **注意**：
  - shadcn Button 默认样式可能与原有 `btn-primary` 有细微差异，需通过 variant/class 调整
  - RoundedSelect 的 `options: [{value, label}]` 接口需改为 SelectItem 子组件模式
  - shadcn Dialog 基于 reka-ui，需确认事件模型兼容

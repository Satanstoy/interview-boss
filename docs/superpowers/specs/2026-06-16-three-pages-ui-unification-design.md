# 三页面 UI 统一设计规范

## 概述

将高频题库、JD库、面经库三个页面的 UI 统一到 shadcn-vue 官方组件体系，消除自定义组件碎片化。

## 目标

- 三个页面使用统一的页面壳结构（筛选栏 + 内容区 + 分页/操作栏）
- 全部使用 shadcn 官方组件，替换自定义 DataTable/PaginationBar/AppEmpty 等
- MasterBank 使用 Accordion 实现可折叠题目卡片
- JD/Interview 使用 Table（已有）+ 统一筛选栏

## 需要安装的 shadcn 组件

通过 `npx shadcn-vue@latest add <component>` 安装：

| 组件 | 用途 | 优先级 |
|------|------|--------|
| `accordion` | MasterBank 可折叠题目列表 | P0 |
| `pagination` | 三个页面统一分页（替换 PaginationBar） | P0 |
| `empty` | 三个页面统一空状态（替换 AppEmpty） | P1 |
| `spinner` | 统一加载指示器 | P2 |

已有的组件直接使用：Table, Card, Badge, Select, Input, Button, Collapsible, DropdownMenu, Checkbox, Separator, Tabs, Tooltip, ScrollArea, Skeleton。

## 页面壳结构（三页统一）

```
┌──────────────────────────────────────────┐
│ 页头区（Card）                             │
│ ┌─ 图标 + 标题 + 副标题 ───────────────┐  │
│ │ 🟣 高频题库                           │  │
│ │    管理和练习面试高频题目               │  │
│ └──────────────────────────────────────┘  │
│ 筛选栏                                    │
│ [搜索 Input] [难度 Select] [分类 Badge组]  │
├──────────────────────────────────────────┤
│ 批量操作栏（BatchActionPanel）             │
│ [全选] [反选] | [删除] [导出] ...          │
├──────────────────────────────────────────┤
│ 内容区                                    │
│ （Accordion / Table / 卡片列表）           │
├──────────────────────────────────────────┤
│ 分页栏（shadcn Pagination）               │
│ 共 N 条  [< 1 2 3 ... 10 >]  每页 [20▾]  │
└──────────────────────────────────────────┘
```

## 高频题库（MasterBank）

### 当前实现
- MasterBankView.vue（197 行）：注入 appData，组装筛选+列表
- MasterBankList.vue（237 行）：虚拟滚动 + QuestionCard
- SearchFilterBar.vue（73 行）：自定义搜索+难度筛选
- QuestionCard.vue：复杂卡片组件（展开/折叠/编辑/答案/标签/操作）

### 改为
- 用 shadcn **Accordion**（`type="multiple"`）实现题目列表
- 每道题是一个 `AccordionItem`：
  - `AccordionTrigger`：题目标题 + 难度 Badge + 标签 Badge + 收藏星标
  - `AccordionContent`：题目描述 + 参考答案 + 操作按钮行（编辑/生成答案/删除等）
- 用 shadcn **Select** 替换 SearchFilterBar 的难度下拉
- 用 shadcn **Input** 替换搜索框
- 用 shadcn **Badge** 渲染分类标签（已有）
- 保留 BatchActionPanel（复用）
- 用 shadcn **Pagination** 替换无限滚动（分页更一致）
- 用 shadcn **Empty** 替换 AppEmpty

### 保留的功能
- 分类标签筛选（pill 按钮组）
- 子标签筛选
- 批量操作（全选/反选/删除/导出）
- 展开/折叠全部
- 收藏/取消收藏
- 内联编辑（题目/答案）
- 生成 AI 答案
- 练习模式
- ExamDistribution 图表

### 移除的自定义组件
- SearchFilterBar → 用 shadcn Input + Select 替代
- AppEmpty → 用 shadcn Empty 替代
- 自定义 PaginationBar → 用 shadcn Pagination 替代

## JD库

### 当前实现
- JdView.vue（73 行）：DataTable + 列定义
- 使用自定义 DataTable（含 shadcn Table + BatchActionPanel + PaginationBar）

### 改为
- 保留 shadcn **Table** 作为表格基础
- DataTable 组件升级：用 shadcn **Pagination** 替换 PaginationBar
- 添加统一的页头 Card（图标 + "JD库" + 副标题）
- 用 shadcn **Empty** 替换空状态
- 列定义和行操作不变

### 保留的功能
- 表格列（公司/岗位/薪资/技术栈/加分项/招聘季）
- 内联编辑（InlineEdit）
- 批量操作
- 分页
- 行操作（链接/删除）

## 面经库

### 当前实现
- InterviewView.vue（137 行）：筛选栏 + DataTable + 浮动返回按钮
- 使用自定义 DataTable + shadcn Select 筛选

### 改为
- 保留 shadcn **Table** 作为表格基础
- DataTable 组件升级：用 shadcn **Pagination** 替换 PaginationBar
- 添加统一的页头 Card（图标 + "面经库" + 副标题）
- 筛选栏样式统一（Select + 排序按钮用 shadcn Button/Toggle）
- 用 shadcn **Empty** 替换空状态
- 浮动返回按钮保留

### 保留的功能
- 季节筛选
- 排序切换
- 表格列（公司/季节/轮次/重点/题目/难度/日期）
- 内联编辑（InlineEdit）
- 重新分析
- 批量操作
- 分页
- 高亮行
- 浮动返回按钮

## 共享组件变更

### DataTable.vue → 重构为 shadcn 原生
- 移除自定义 PaginationBar，改用 shadcn Pagination
- 移除自定义空状态，改用 shadcn Empty
- 保留 BatchActionPanel（已有）
- 保留 shadcn Table 基础结构

### PaginationBar.vue → 废弃
- 替换为 shadcn Pagination
- 迁移所有使用方

### AppEmpty.vue → 废弃
- 替换为 shadcn Empty
- 迁移 MasterBankList 的使用

### BatchActionPanel.vue → 保留
- 三个页面都使用，保持不变

## 实施顺序

1. 安装新 shadcn 组件（accordion, pagination, empty）
2. 重构 PaginationBar → shadcn Pagination（影响 DataTable → JD + Interview）
3. 升级 DataTable 使用新 Pagination
4. 统一 JD 和 Interview 的页头结构
5. 重构 MasterBank 使用 Accordion
6. 统一三个页面的筛选栏样式
7. 用 shadcn Empty 替换所有自定义空状态

## 验证

- `npm run build` 无报错
- 三个页面功能完整（筛选/分页/批量操作/内联编辑）
- 暗色模式正常
- 响应式布局正常（移动端/桌面端）

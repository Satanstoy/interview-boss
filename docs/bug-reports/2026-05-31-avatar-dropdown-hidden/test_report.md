# 测试验证报告

**Bug ID:** BUG-001
**日期:** 2026-05-31
**状态:** ✅ 已修复

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 前端构建 | ✅ 成功（11.16s） |
| 后端测试 | ✅ 无回归（3个预先存在的 proxy 错误，与本次修改无关） |
| 修复状态 | ✅ 成功 |

## 2. 根因分析

提交 `8947631`（fix: 320px 小屏幕导航栏和 Tab 栏溢出修复）为了解决极小屏幕下导航栏的水平溢出问题，在导航栏容器（`App.vue:5`）上添加了 `overflow-hidden` 类。该容器同时设置了 `h-14`（固定高度 56px）。

UserMenu 的下拉菜单使用 `position: absolute; top: 100%` 定位，位于头像按钮正下方，即容器底部以下。`overflow: hidden` 将其完全裁剪。

## 3. 修复方案

使用 Vue `<Teleport to="body">` 将下拉菜单和点击遮罩传送到 `<body>` 元素：

**修改文件:** `frontend/src/components/business/UserMenu.vue`

| 变更 | 说明 |
|------|------|
| 添加 `<Teleport to="body">` | 下拉菜单脱离 overflow-hidden 容器 |
| `position: absolute` → `position: fixed` | Teleport 后相对于 viewport 定位 |
| 添加 `buttonRef` + 位置计算 | 使用 getBoundingClientRect 精确定位 |
| 监听 scroll/resize | 滚动/缩放时动态更新菜单位置 |
| `scoped` CSS → 全局 CSS | Teleport 后 scoped 样式不生效 |

## 4. 代码变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `frontend/src/components/business/UserMenu.vue` | 修改 | Teleport 下拉菜单到 body，添加位置计算逻辑 |

## 5. 结论

- [x] 根因已确认（overflow-hidden 裁剪）
- [x] 修复已实施（Teleport + fixed positioning）
- [x] 前端构建通过
- [x] 无后端回归
- [x] 保留了 320px 小屏幕修复

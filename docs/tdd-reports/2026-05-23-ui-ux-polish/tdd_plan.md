# TDD 开发计划

**功能名称:** UI/UX 精致化升级（动画系统 + 视觉深度 + 加载状态 + 响应式）
**日期:** 2026-05-23
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

将前端从"功能可用"提升到"精致可用"：引入 @vueuse/motion 动画系统、增强视觉层次、统一加载/空状态、支持响应式和可访问性。

## 验收标准

- [ ] @vueuse/motion 已安装并全局配置，提供 fade-in / slide-up / stagger 预设
- [ ] Tab 切换有流畅的入场动画（motion-based）
- [ ] 卡片列表有 stagger 入场效果
- [ ] 按钮有 press 微交互反馈
- [ ] Modal 组件统一使用共享模式（teleport + backdrop + transition）
- [ ] 加载状态使用 skeleton 而非纯文本
- [ ] 空状态有图标/插图引导
- [ ] `prefers-reduced-motion` 被尊重
- [ ] 移动端有基本适配（sm/md 断点）
- [ ] prose-chat 样式统一

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | Motion 插件已注册 | 访问页面 | `v-motion` 指令可用，元素有 motion 属性 | ⏳ 待写 |
| T-002 | Tab 切换动画 | 点击不同 Tab | 内容区域有入场过渡效果 | ⏳ 待写 |
| T-003 | 卡片 stagger 入场 | 加载题库列表 | 卡片依次出现而非同时 | ⏳ 待写 |
| T-004 | 按钮 press 反馈 | 点击按钮 | 按钮有 scale 缩放反馈 | ⏳ 待写 |
| T-005 | Modal 统一模式 | 打开设置/登录 Modal | 有 teleport + backdrop + fade 过渡 | ⏳ 待写 |
| T-006 | Skeleton 加载状态 | 触发数据加载 | 显示 skeleton 骨架屏而非"加载中..." | ⏳ 待写 |
| T-007 | 空状态设计 | 清空数据 | 显示图标引导而非纯文本 | ⏳ 待写 |
| T-008 | Reduced motion | prefers-reduced-motion: reduce | 动画被禁用或简化 | ⏳ 待写 |
| T-009 | 移动端适配 | 窄屏访问 | 布局自适应，Tab 不溢出 | ⏳ 待写 |

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 — Motion 插件注册与配置
- [ ] 循环 2: T-002 — Tab 切换动画
- [ ] 循环 3: T-003 — 卡片 stagger 入场
- [ ] 循环 4: T-004 — 按钮 press 微交互
- [ ] 循环 5: T-005 — Modal 统一
- [ ] 循环 6: T-006 — Skeleton 加载
- [ ] 循环 7: T-007 — 空状态设计
- [ ] 循环 8: T-008 — Reduced motion
- [ ] 循环 9: T-009 — 移动端适配

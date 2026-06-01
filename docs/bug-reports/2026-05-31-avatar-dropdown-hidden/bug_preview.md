# Bug 预览报告

**日期:** 2026-05-31
**问题:** 点击用户头像后下拉菜单不可见（被 CSS overflow-hidden 裁剪）
**严重程度:** Critical

## 初步诊断

### 问题现象
用户点击导航栏右侧的头像按钮后，下拉菜单（包含个人信息、题库模式切换、退出登录等选项）完全不显示。按钮本身可以点击（`showMenu` ref 状态会切换），但下拉内容被父容器裁剪不可见。

### 根本原因
提交 `8947631`（fix: 320px 小屏幕导航栏和 Tab 栏溢出修复）在导航栏内容容器上添加了 `overflow-hidden` 类：

```html
<!-- App.vue line 5 -->
<div class="max-w-[1920px] mx-auto px-3 sm:px-5 lg:px-8 h-14 flex items-center justify-between overflow-hidden">
```

该容器的固定高度为 `h-14`（56px），而 UserMenu 的下拉菜单使用 `position: absolute; top: 100%` 定位，**位于容器底部下方**。`overflow: hidden` 会裁剪所有超出容器边界的内容，包括下方的下拉菜单。

**溢出裁剪链：**
```
nav (z-50)
  └─ div.overflow-hidden.h-14 (固定高度 56px，裁剪下方内容)
       └─ UserMenu (.relative)
            └─ button (头像按钮)
            └─ dropdown (absolute, top: 100%, 在容器下方 → 被裁剪!)
            └─ click-outside overlay (fixed, inset-0, z-40)
```

### 影响范围
- **功能:** 头像下拉菜单（个人信息、题库模式切换、审核题库、退出登录）全部不可用
- **用户:** 所有用户（管理员和普通用户）
- **数据:** 不影响数据完整性

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Critical | 核心导航菜单完全不可用 |
| 数据完整性 | None | 不涉及数据操作 |
| 安全风险 | Low | 退出登录功能被隐藏（但可通过其他方式登出） |

# Bug 验证报告

**Bug ID:** BUG-001
**验证日期:** 2026-05-31

## 可追溯性矩阵

| Bug ID | Bug 描述 | 根因文件 | 修复文件 | 覆盖状态 |
|--------|---------|---------|---------|---------|
| BUG-001 | overflow-hidden 裁剪下拉菜单 | `App.vue:5` | `UserMenu.vue` | ✅ 已修复 |

## 修复方案

使用 Vue `<Teleport to="body">` 将下拉菜单和点击遮罩传送到 `<body>` 元素，脱离导航栏的 `overflow: hidden` 约束。

### 关键变更
1. 下拉菜单从 `position: absolute` 改为 `position: fixed`（Teleport 后相对于 viewport 定位）
2. 添加 `buttonRef` 获取头像按钮的屏幕坐标，计算下拉菜单精确位置
3. 监听 scroll/resize 事件，动态更新菜单位置
4. 过渡动画样式从 `scoped` 改为全局（Teleport 后 scoped CSS 不生效）

## 测试结果

**前端构建:**
```
✓ built in 11.16s
```
✅ 构建成功，无错误

**后端测试:**
预先存在的 3 个 proxy 相关 collection 错误（socks5h），与本次前端修改无关。

## 验证步骤（手动）

1. 登录系统
2. 点击用户头像 → 应看到下拉菜单
3. 确认菜单中包含：用户名、题库模式切换、个人信息、退出登录
4. 点击"个人信息" → ProfilePanel 正常弹出
5. 点击菜单外部 → 下拉菜单关闭
6. 缩小窗口到 320px → 导航栏水平方向不溢出
7. 在有滚动的页面上点击头像 → 菜单位置正确

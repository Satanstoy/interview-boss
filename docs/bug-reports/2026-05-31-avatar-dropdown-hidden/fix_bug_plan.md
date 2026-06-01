# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-31
**优先级:** P0（Critical）

## 修复步骤

### 步骤 1: 使用 Teleport 将下拉菜单传送到 body
**文件:** `frontend/src/components/business/UserMenu.vue`
**行号:** 14-88
**修改类型:** 修改

**修改前:**
```html
<!-- Dropdown -->
<Transition name="menu">
  <div v-if="showMenu" class="absolute right-0 top-full mt-2 w-60 ...">
    ...
  </div>
</Transition>

<!-- Click outside -->
<div v-if="showMenu" class="fixed inset-0 z-40" @click="showMenu = false"></div>
```

**修改后:**
```html
<Teleport to="body">
  <!-- Click outside -->
  <div v-if="showMenu" class="fixed inset-0 z-40" @click="showMenu = false"></div>

  <!-- Dropdown -->
  <Transition name="menu">
    <div v-if="showMenu" ref="dropdownRef" class="fixed w-60 ...">
      ...
    </div>
  </Transition>
</Teleport>
```

关键变更：
- 使用 `<Teleport to="body">` 将下拉菜单和遮罩渲染到 body 元素，脱离 `overflow: hidden` 容器
- 下拉菜单从 `position: absolute` 改为 `position: fixed`（因为 Teleport 后不再相对于父元素定位）
- 使用 JavaScript 计算下拉菜单的精确位置（基于头像按钮的位置）
- 点击遮罩保持 `position: fixed`

## 验证方法
1. 登录系统
2. 点击用户头像 → 下拉菜单正常显示
3. 下拉菜单中可以看到"题库模式"切换、"个人信息"、"退出登录"等选项
4. 点击"个人信息" → ProfilePanel 正常弹出
5. 点击菜单外部 → 下拉菜单关闭
6. 缩小窗口到 320px → 导航栏不溢出水平方向

## 回滚方案
还原 `UserMenu.vue` 的修改，恢复到 `<Teleport>` 之前的版本。

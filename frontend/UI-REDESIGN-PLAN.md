# InterviewBoss 前端 UI 重设计执行计划

## 概述

将现有 Vue3 + JavaScript 前端重设计为现代 SaaS/管理后台风格，使用 shadcn-vue 组件库。

**目标**：统一视觉风格、提升用户体验、保持业务逻辑不变

**约束**：
- ❌ 不改业务逻辑
- ❌ 不改后端 API
- ❌ 不改路由结构（Layout 集成除外）
- ❌ 不迁移到 TypeScript
- ✅ 保持 Vue3 + JavaScript
- ✅ 必须通过 `npm install`、`npm run dev`、`npm run build`

## 当前状态分析

### 已有 shadcn-vue 组件（17 个）
- ✅ avatar, badge, button, card, chart, checkbox, dropdown-menu, input, label, select, separator, sheet, sidebar, skeleton, table, tabs, tooltip

### 已有基础设施
- ✅ `components.json` 配置文件（shadcn-vue 初始化完成）
- ✅ `src/lib/utils.ts`（cn 函数）
- ✅ `AppSidebar.vue`（使用 shadcn-vue Sidebar 组件）
- ✅ `SiteHeader.vue`（使用 shadcn-vue Button, Separator, SidebarTrigger）
- ✅ `SidebarProvider` + `SidebarInset` 布局结构

### 需要安装的 shadcn-vue 组件（9 个）
- ❌ dialog（对话框）
- ❌ sonner（toast 通知）
- ❌ form（表单验证）
- ❌ breadcrumb（面包屑）
- ❌ alert（提示框）
- ❌ scroll-area（滚动区域）
- ❌ collapsible（折叠面板）
- ❌ popover（弹出框）
- ❌ command（命令面板）

---

## Phase 1: 基础设施准备（1-2 小时）

### Task 1.1: 修复 TypeScript 兼容性
**Files:**
- Create: `frontend/src/lib/utils.js`
- Modify: `frontend/components.json`

**步骤:**
- [ ] Step 1: 创建 `src/lib/utils.js`（从 utils.ts 复制，移除类型注解）
- [ ] Step 2: 修改 `components.json` 将 `typescript: true` 改为 `typescript: false`
- [ ] Step 3: 运行 `cd frontend && npm run build` 验证编译通过

**验证:** `npm run build` 成功，无 TypeScript 错误

**utils.js 内容:**
```javascript
import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}
```

---

### Task 1.2: 安装缺失的 shadcn-vue 组件
**Files:**
- Create: `frontend/src/components/ui/dialog/`（dialog 组件）
- Create: `frontend/src/components/ui/sonner/`（toast 组件）
- Create: `frontend/src/components/ui/form/`（form 组件）
- Create: `frontend/src/components/ui/breadcrumb/`（breadcrumb 组件）
- Create: `frontend/src/components/ui/alert/`（alert 组件）
- Create: `frontend/src/components/ui/scroll-area/`（scroll-area 组件）
- Create: `frontend/src/components/ui/collapsible/`（collapsible 组件）
- Create: `frontend/src/components/ui/popover/`（popover 组件）
- Create: `frontend/src/components/ui/command/`（command 组件）

**步骤:**
- [ ] Step 1: 运行 `cd frontend && npx shadcn-vue@latest add dialog`
- [ ] Step 2: 运行 `cd frontend && npx shadcn-vue@latest add sonner`
- [ ] Step 3: 运行 `cd frontend && npx shadcn-vue@latest add form`
- [ ] Step 4: 运行 `cd frontend && npx shadcn-vue@latest add breadcrumb`
- [ ] Step 5: 运行 `cd frontend && npx shadcn-vue@latest add alert`
- [ ] Step 6: 运行 `cd frontend && npx shadcn-vue@latest add scroll-area`
- [ ] Step 7: 运行 `cd frontend && npx shadcn-vue@latest add collapsible`
- [ ] Step 8: 运行 `cd frontend && npx shadcn-vue@latest add popover`
- [ ] Step 9: 运行 `cd frontend && npx shadcn-vue@latest add command`
- [ ] Step 10: 运行 `cd frontend && npm run build` 验证所有组件安装成功

**验证:** 所有组件目录存在，`npm run build` 通过

**注意:** 如果 `npx shadcn-vue@latest add` 失败，可以手动创建组件文件，参考 shadcn-vue 官方文档

---

### Task 1.3: 创建全局主题配置
**Files:**
- Create: `frontend/src/assets/styles/theme.css`
- Modify: `frontend/src/assets/styles/global.css`

**步骤:**
- [ ] Step 1: 创建 `theme.css`，定义 CSS 变量（颜色、间距、圆角、阴影）
- [ ] Step 2: 在 `global.css` 中导入 `theme.css`
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证样式生效

**验证:** 浏览器开发者工具中看到 CSS 变量已定义

**theme.css 内容:**
```css
:root {
  /* 颜色 */
  --color-primary: #0f172a;
  --color-primary-foreground: #f8fafc;
  --color-secondary: #f1f5f9;
  --color-secondary-foreground: #0f172a;
  --color-muted: #f1f5f9;
  --color-muted-foreground: #64748b;
  --color-accent: #f1f5f9;
  --color-accent-foreground: #0f172a;
  --color-destructive: #ef4444;
  --color-destructive-foreground: #f8fafc;
  --color-border: #e2e8f0;
  --color-input: #e2e8f0;
  --color-ring: #0f172a;
  --color-background: #ffffff;
  --color-foreground: #0f172a;
  --color-card: #ffffff;
  --color-card-foreground: #0f172a;
  --color-popover: #ffffff;
  --color-popover-foreground: #0f172a;

  /* 间距 */
  --spacing-xs: 0.25rem;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --spacing-xl: 2rem;
  --spacing-2xl: 3rem;

  /* 圆角 */
  --radius-sm: 0.25rem;
  --radius-md: 0.375rem;
  --radius-lg: 0.5rem;
  --radius-xl: 0.75rem;
  --radius-2xl: 1rem;

  /* 阴影 */
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
  --shadow-xl: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1);
}

.dark {
  --color-primary: #f8fafc;
  --color-primary-foreground: #0f172a;
  --color-secondary: #1e293b;
  --color-secondary-foreground: #f8fafc;
  --color-muted: #1e293b;
  --color-muted-foreground: #94a3b8;
  --color-accent: #1e293b;
  --color-accent-foreground: #f8fafc;
  --color-destructive: #ef4444;
  --color-destructive-foreground: #f8fafc;
  --color-border: #334155;
  --color-input: #334155;
  --color-ring: #f8fafc;
  --color-background: #0f172a;
  --color-foreground: #f8fafc;
  --color-card: #0f172a;
  --color-card-foreground: #f8fafc;
  --color-popover: #0f172a;
  --color-popover-foreground: #f8fafc;
}
```

---

## Phase 2: 统一布局组件（2-3 小时）

### Task 2.1: 重构 AppSidebar
**Files:**
- Modify: `frontend/src/components/AppSidebar.vue`

**步骤:**
- [ ] Step 1: 使用 shadcn-vue Sidebar 组件重构
- [ ] Step 2: 添加 Logo、导航菜单、用户头像
- [ ] Step 3: 支持折叠/展开
- [ ] Step 4: 运行 `npm run dev` 验证侧边栏显示正常

**验证:** 侧边栏显示 Logo、导航项、用户头像，可折叠

---

### Task 2.2: 创建 SiteHeader 组件
**Files:**
- Create: `frontend/src/components/SiteHeader.vue`

**步骤:**
- [ ] Step 1: 创建 `SiteHeader.vue`，包含面包屑、搜索框、用户菜单
- [ ] Step 2: 使用 shadcn-vue Breadcrumb 组件
- [ ] Step 3: 使用 shadcn-vue DropdownMenu 组件
- [ ] Step 4: 运行 `npm run dev` 验证头部显示正常

**验证:** 头部显示面包屑、搜索框、用户下拉菜单

---

### Task 2.3: 重构 DefaultLayout
**Files:**
- Modify: `frontend/src/layouts/DefaultLayout.vue`

**步骤:**
- [ ] Step 1: 使用 shadcn-vue SidebarProvider 包装
- [ ] Step 2: 集成 AppSidebar、SiteHeader
- [ ] Step 3: 添加主内容区域（SidebarInset）
- [ ] Step 4: 运行 `npm run dev` 验证布局显示正常

**验证:** 完整布局显示：侧边栏 + 头部 + 主内容区

---

### Task 2.4: 更新 App.vue 集成新布局
**Files:**
- Modify: `frontend/src/App.vue`

**步骤:**
- [ ] Step 1: 在 App.vue 中集成 DefaultLayout
- [ ] Step 2: 将 TabBar 替换为侧边栏导航
- [ ] Step 3: 运行 `npm run dev` 验证整体布局

**验证:** 应用显示完整布局，Tab 切换正常工作

---

## Phase 3: 项目级 UI 组件（3-4 小时）

### Task 3.1: 创建 AppPage 组件
**Files:**
- Create: `frontend/src/components/common/AppPage.vue`

**步骤:**
- [ ] Step 1: 创建 `AppPage.vue`，提供页面容器样式
- [ ] Step 2: 支持标题、描述、操作按钮
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 页面容器显示标题、描述、操作区域

**AppPage.vue 内容:**
```vue
<script setup>
defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  showBack: { type: Boolean, default: false }
})

const emit = defineEmits(['back'])
</script>

<template>
  <div class="min-h-screen bg-background">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div v-if="title || $slots.header" class="mb-6">
        <div class="flex items-center justify-between">
          <div>
            <div v-if="showBack" class="mb-2">
              <button
                @click="emit('back')"
                class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
                </svg>
                返回
              </button>
            </div>
            <h1 class="text-2xl font-bold tracking-tight text-foreground">{{ title }}</h1>
            <p v-if="description" class="mt-1 text-sm text-muted-foreground">{{ description }}</p>
          </div>
          <div v-if="$slots.actions" class="flex items-center gap-2">
            <slot name="actions" />
          </div>
        </div>
      </div>
      <slot />
    </div>
  </div>
</template>
```

---

### Task 3.2: 创建 AppPageHeader 组件
**Files:**
- Create: `frontend/src/components/common/AppPageHeader.vue`

**步骤:**
- [ ] Step 1: 创建 `AppPageHeader.vue`，提供页面头部样式
- [ ] Step 2: 支持标题、描述、操作按钮、返回按钮
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 页面头部显示标题、描述、操作按钮

**AppPageHeader.vue 内容:**
```vue
<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  showBack: { type: Boolean, default: false }
})

const emit = defineEmits(['back'])
</script>

<template>
  <div class="flex items-center justify-between">
    <div>
      <div v-if="showBack" class="mb-2">
        <button
          @click="emit('back')"
          class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          返回
        </button>
      </div>
      <h1 class="text-2xl font-bold tracking-tight text-foreground">{{ title }}</h1>
      <p v-if="description" class="mt-1 text-sm text-muted-foreground">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="flex items-center gap-2">
      <slot name="actions" />
    </div>
  </div>
</template>
```

---

### Task 3.3: 创建 AppCard 组件
**Files:**
- Create: `frontend/src/components/common/AppCard.vue`

**步骤:**
- [ ] Step 1: 创建 `AppCard.vue`，包装 shadcn-vue Card
- [ ] Step 2: 添加标题、描述、内容、操作区域
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 卡片组件显示标题、描述、内容、操作区域

**AppCard.vue 内容:**
```vue
<script setup>
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle
} from '@/components/ui/card'

defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  noPadding: { type: Boolean, default: false }
})
</script>

<template>
  <Card class="rounded-xl border-border bg-card shadow-sm">
    <CardHeader v-if="title || $slots.header" class="border-b border-border px-4 py-3">
      <div v-if="$slots.header" class="flex items-center justify-between">
        <slot name="header" />
      </div>
      <template v-else>
        <CardTitle class="text-sm font-semibold text-card-foreground">{{ title }}</CardTitle>
        <CardDescription v-if="description" class="text-xs text-muted-foreground">{{ description }}</CardDescription>
      </template>
    </CardHeader>
    <CardContent :class="noPadding ? 'p-0' : 'p-4'">
      <slot />
    </CardContent>
    <CardFooter v-if="$slots.footer" class="border-t border-border px-4 py-3">
      <slot name="footer" />
    </CardFooter>
  </Card>
</template>
```

---

### Task 3.4: 创建 AppTable 组件
**Files:**
- Create: `frontend/src/components/common/AppTable.vue`

**步骤:**
- [ ] Step 1: 创建 `AppTable.vue`，包装 shadcn-vue Table
- [ ] Step 2: 添加分页、排序、筛选功能
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 表格组件显示数据、分页、排序、筛选功能

**AppTable.vue 内容:**
```vue
<script setup>
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table'

defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, required: true },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' }
})
</script>

<template>
  <div class="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
    <Table>
      <TableHeader>
        <TableRow class="bg-muted/50">
          <TableHead v-for="col in columns" :key="col.key" class="text-xs font-semibold text-muted-foreground">
            {{ col.label }}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow v-if="loading">
          <TableCell :colspan="columns.length" class="h-24 text-center text-muted-foreground">
            <div class="flex items-center justify-center gap-2">
              <svg class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              加载中...
            </div>
          </TableCell>
        </TableRow>
        <TableRow v-else-if="rows.length === 0">
          <TableCell :colspan="columns.length" class="h-24 text-center text-muted-foreground">
            {{ emptyText }}
          </TableCell>
        </TableRow>
        <TableRow v-else v-for="row in rows" :key="row.id" class="hover:bg-muted/50 transition-colors">
          <TableCell v-for="col in columns" :key="col.key" class="text-sm">
            <slot :name="`cell-${col.key}`" :row="row">
              {{ row[col.key] }}
            </slot>
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>
  </div>
</template>
```

---

### Task 3.5: 创建 AppSearchForm 组件
**Files:**
- Create: `frontend/src/components/common/AppSearchForm.vue`

**步骤:**
- [ ] Step 1: 创建 `AppSearchForm.vue`，提供搜索表单样式
- [ ] Step 2: 支持输入框、选择框、日期选择器
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 搜索表单显示输入框、选择框、筛选按钮

**AppSearchForm.vue 内容:**
```vue
<script setup>
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '搜索...' },
  showSearch: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'search', 'reset'])
</script>

<template>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
    <div class="relative flex-1">
      <svg class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <Input
        :model-value="modelValue"
        @update:model-value="emit('update:modelValue', $event)"
        :placeholder="placeholder"
        class="pl-9"
        @keyup.enter="emit('search')"
      />
    </div>
    <div v-if="showSearch" class="flex items-center gap-2">
      <Button variant="outline" size="sm" @click="emit('reset')">
        重置
      </Button>
      <Button size="sm" @click="emit('search')">
        搜索
      </Button>
    </div>
    <slot name="filters" />
  </div>
</template>
```

---

### Task 3.6: 创建 AppDialog 组件
**Files:**
- Create: `frontend/src/components/common/AppDialog.vue`

**步骤:**
- [ ] Step 1: 创建 `AppDialog.vue`，包装 shadcn-vue Dialog
- [ ] Step 2: 添加标题、描述、内容、操作按钮
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 对话框组件显示标题、描述、内容、操作按钮

**AppDialog.vue 内容:**
```vue
<script setup>
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  maxWidth: { type: String, default: 'max-w-lg' }
})

const emit = defineEmits(['update:open', 'close'])
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent :class="maxWidth">
      <DialogHeader>
        <DialogTitle>{{ title }}</DialogTitle>
        <DialogDescription v-if="description">{{ description }}</DialogDescription>
      </DialogHeader>
      <div class="py-4">
        <slot />
      </div>
      <DialogFooter v-if="$slots.footer">
        <slot name="footer" />
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
```

---

### Task 3.7: 创建 AppEmpty 组件
**Files:**
- Create: `frontend/src/components/common/AppEmpty.vue`

**步骤:**
- [ ] Step 1: 创建 `AppEmpty.vue`，提供空状态样式
- [ ] Step 2: 支持图标、标题、描述、操作按钮
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 空状态组件显示图标、标题、描述、操作按钮

**AppEmpty.vue 内容:**
```vue
<script setup>
defineProps({
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
  icon: { type: String, default: 'empty' }
})
</script>

<template>
  <div class="flex flex-col items-center justify-center py-12 text-center">
    <div class="mb-4 rounded-full bg-muted p-4">
      <svg class="h-8 w-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
      </svg>
    </div>
    <h3 class="mb-1 text-sm font-semibold text-foreground">{{ title }}</h3>
    <p v-if="description" class="mb-4 text-sm text-muted-foreground">{{ description }}</p>
    <slot />
  </div>
</template>
```

---

### Task 3.8: 创建 AppLoading 组件
**Files:**
- Create: `frontend/src/components/common/AppLoading.vue`

**步骤:**
- [ ] Step 1: 创建 `AppLoading.vue`，提供加载状态样式
- [ ] Step 2: 支持骨架屏、加载动画
- [ ] Step 3: 运行 `cd frontend && npm run dev` 验证组件显示

**验证:** 加载组件显示骨架屏或加载动画

**AppLoading.vue 内容:**
```vue
<script setup>
defineProps({
  type: { type: String, default: 'spinner' }, // spinner | skeleton | cards
  rows: { type: Number, default: 3 }
})
</script>

<template>
  <div v-if="type === 'spinner'" class="flex items-center justify-center py-12">
    <svg class="animate-spin h-8 w-8 text-primary" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
    </svg>
  </div>
  <div v-else-if="type === 'skeleton'" class="space-y-3">
    <div v-for="i in rows" :key="i" class="flex items-center gap-3">
      <div class="h-10 w-10 rounded-lg bg-muted animate-pulse"></div>
      <div class="flex-1 space-y-2">
        <div class="h-4 w-3/4 rounded bg-muted animate-pulse"></div>
        <div class="h-3 w-1/2 rounded bg-muted animate-pulse"></div>
      </div>
    </div>
  </div>
  <div v-else-if="type === 'cards'" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
    <div v-for="i in rows" :key="i" class="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div class="mb-3 flex items-center gap-3">
        <div class="h-10 w-10 rounded-lg bg-muted animate-pulse"></div>
        <div class="flex-1 space-y-2">
          <div class="h-4 w-3/4 rounded bg-muted animate-pulse"></div>
          <div class="h-3 w-1/2 rounded bg-muted animate-pulse"></div>
        </div>
      </div>
      <div class="space-y-2">
        <div class="h-3 w-full rounded bg-muted animate-pulse"></div>
        <div class="h-3 w-5/6 rounded bg-muted animate-pulse"></div>
        <div class="h-3 w-4/6 rounded bg-muted animate-pulse"></div>
      </div>
    </div>
  </div>
</template>
```

---

## Phase 4: 页面重构 - 登录页面（1-2 小时）

### Task 4.1: 重构 LoginPage
**Files:**
- Modify: `frontend/src/components/business/LoginPage.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard、AppPage 组件重构
- [ ] Step 2: 使用 shadcn-vue Form 组件
- [ ] Step 3: 添加表单验证
- [ ] Step 4: 运行 `npm run dev` 验证登录页面

**验证:** 登录页面显示现代化设计，表单验证正常

---

### Task 4.2: 重构 LoginModal
**Files:**
- Modify: `frontend/src/components/business/LoginModal.vue`

**步骤:**
- [ ] Step 1: 使用 AppDialog 组件重构
- [ ] Step 2: 使用 shadcn-vue Form 组件
- [ ] Step 3: 运行 `npm run dev` 验证登录弹窗

**验证:** 登录弹窗显示现代化设计，表单验证正常

---

## Phase 5: 页面重构 - 题库管理（2-3 小时）

### Task 5.1: 重构 MasterBankList
**Files:**
- Modify: `frontend/src/components/business/MasterBankList.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppTable 组件重构
- [ ] Step 2: 使用 AppSearchForm 组件
- [ ] Step 3: 使用 AppEmpty、AppLoading 组件
- [ ] Step 4: 运行 `npm run dev` 验证题库列表

**验证:** 题库列表显示现代化设计，搜索、分页、筛选正常

---

### Task 5.2: 重构 QuestionCard
**Files:**
- Modify: `frontend/src/components/business/QuestionCard.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard 组件重构
- [ ] Step 2: 添加标签、难度、操作按钮
- [ ] Step 3: 运行 `npm run dev` 验证题目卡片

**验证:** 题目卡片显示现代化设计，标签、难度、操作正常

---

### Task 5.3: 重构 SearchFilterBar
**Files:**
- Modify: `frontend/src/components/business/SearchFilterBar.vue`

**步骤:**
- [ ] Step 1: 使用 AppSearchForm 组件重构
- [ ] Step 2: 使用 shadcn-vue Select、Input 组件
- [ ] Step 3: 运行 `npm run dev` 验证搜索筛选栏

**验证:** 搜索筛选栏显示现代化设计，筛选功能正常

---

## Phase 6: 页面重构 - 练习与面试（2-3 小时）

### Task 6.1: 重构 PracticePanel
**Files:**
- Modify: `frontend/src/components/business/PracticePanel.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppCard 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证练习面板

**验证:** 练习面板显示现代化设计，功能正常

---

### Task 6.2: 重构 PracticeMode
**Files:**
- Modify: `frontend/src/components/business/PracticeMode.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard、AppDialog 组件重构
- [ ] Step 2: 使用 shadcn-vue Button 组件
- [ ] Step 3: 运行 `npm run dev` 验证练习模式

**验证:** 练习模式显示现代化设计，功能正常

---

### Task 6.3: 重构 MockInterview
**Files:**
- Modify: `frontend/src/components/business/MockInterview.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppCard 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证模拟面试

**验证:** 模拟面试显示现代化设计，功能正常

---

## Phase 7: 页面重构 - 对话与代码（2-3 小时）

### Task 7.1: 重构 ChatView
**Files:**
- Modify: `frontend/src/components/business/ChatView.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppCard 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证对话视图

**验证:** 对话视图显示现代化设计，功能正常

---

### Task 7.2: 重构 ChatMessage
**Files:**
- Modify: `frontend/src/components/business/ChatMessage.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard 组件重构
- [ ] Step 2: 添加消息气泡样式
- [ ] Step 3: 运行 `npm run dev` 验证消息组件

**验证:** 消息组件显示现代化设计，样式正常

---

### Task 7.3: 重构 CodingPractice
**Files:**
- Modify: `frontend/src/components/business/CodingPractice.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppCard 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证代码练习

**验证:** 代码练习显示现代化设计，功能正常

---

### Task 7.4: 重构 CodeEditor
**Files:**
- Modify: `frontend/src/components/business/CodeEditor.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard 组件重构
- [ ] Step 2: 添加代码编辑器样式
- [ ] Step 3: 运行 `npm run dev` 验证代码编辑器

**验证:** 代码编辑器显示现代化设计，功能正常

---

## Phase 8: 页面重构 - 其他页面（2-3 小时）

### Task 8.1: 重构 SettingsPanel
**Files:**
- Modify: `frontend/src/components/business/SettingsPanel.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppCard 组件重构
- [ ] Step 2: 使用 shadcn-vue Form 组件
- [ ] Step 3: 运行 `npm run dev` 验证设置面板

**验证:** 设置面板显示现代化设计，表单验证正常

---

### Task 8.2: 重构 ProfilePanel
**Files:**
- Modify: `frontend/src/components/business/ProfilePanel.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppCard 组件重构
- [ ] Step 2: 使用 shadcn-vue Form 组件
- [ ] Step 3: 运行 `npm run dev` 验证个人资料

**验证:** 个人资料显示现代化设计，表单验证正常

---

### Task 8.3: 重构 AnalyticsSidebar
**Files:**
- Modify: `frontend/src/components/business/AnalyticsSidebar.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证分析侧边栏

**验证:** 分析侧边栏显示现代化设计，图表正常

---

### Task 8.4: 重构 KnowledgeGraph
**Files:**
- Modify: `frontend/src/components/business/KnowledgeGraph.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证知识图谱

**验证:** 知识图谱显示现代化设计，图表正常

---

### Task 8.5: 重构 AdminReview
**Files:**
- Modify: `frontend/src/components/business/AdminReview.vue`

**步骤:**
- [ ] Step 1: 使用 AppPage、AppTable 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证管理审核

**验证:** 管理审核显示现代化设计，功能正常

---

### Task 8.6: 重构 StagingPanel
**Files:**
- Modify: `frontend/src/components/business/StagingPanel.vue`

**步骤:**
- [ ] Step 1: 使用 AppCard 组件重构
- [ ] Step 2: 使用 AppEmpty、AppLoading 组件
- [ ] Step 3: 运行 `npm run dev` 验证暂存面板

**验证:** 暂存面板显示现代化设计，功能正常

---

### Task 8.7: 重构 MergeQuestionDialog
**Files:**
- Modify: `frontend/src/components/business/MergeQuestionDialog.vue`

**步骤:**
- [ ] Step 1: 使用 AppDialog 组件重构
- [ ] Step 2: 使用 shadcn-vue Form 组件
- [ ] Step 3: 运行 `npm run dev` 验证合并题目对话框

**验证:** 合并题目对话框显示现代化设计，功能正常

---

### Task 8.8: 重构 NewChatModal
**Files:**
- Modify: `frontend/src/components/business/NewChatModal.vue`

**步骤:**
- [ ] Step 1: 使用 AppDialog 组件重构
- [ ] Step 2: 使用 shadcn-vue Form 组件
- [ ] Step 3: 运行 `npm run dev` 验证新建对话弹窗

**验证:** 新建对话弹窗显示现代化设计，功能正常

---

### Task 8.9: 重构 UserMenu
**Files:**
- Modify: `frontend/src/components/business/UserMenu.vue`

**步骤:**
- [ ] Step 1: 使用 shadcn-vue DropdownMenu 组件重构
- [ ] Step 2: 使用 shadcn-vue Avatar 组件
- [ ] Step 3: 运行 `npm run dev` 验证用户菜单

**验证:** 用户菜单显示现代化设计，下拉功能正常

---

## Phase 9: 清理与验证（1-2 小时）

### Task 9.1: 清理旧组件
**Files:**
- Delete: `frontend/src/components/common/BaseModal.vue`（用 AppDialog 替代）
- Delete: `frontend/src/components/common/ConfirmDialog.vue`（用 AppDialog 替代）
- Delete: `frontend/src/components/common/TabBar.vue`（用侧边栏替代）

**步骤:**
- [ ] Step 1: 检查旧组件是否还有引用
- [ ] Step 2: 删除不再使用的旧组件
- [ ] Step 3: 运行 `npm run build` 验证编译通过

**验证:** 无 TypeScript 错误，`npm run build` 通过

---

### Task 9.2: 全局样式统一
**Files:**
- Modify: `frontend/src/assets/styles/global.css`
- Modify: `frontend/src/assets/styles/variables.css`

**步骤:**
- [ ] Step 1: 统一颜色变量（主色、辅色、中性色）
- [ ] Step 2: 统一间距变量（sm、md、lg、xl）
- [ ] Step 3: 统一圆角变量（sm、md、lg）
- [ ] Step 4: 统一阴影变量（sm、md、lg）
- [ ] Step 5: 运行 `npm run dev` 验证样式统一

**验证:** 所有组件使用统一的 CSS 变量

---

### Task 9.3: 最终验证
**Files:**
- None

**步骤:**
- [ ] Step 1: 运行 `cd frontend && npm install` 验证依赖安装
- [ ] Step 2: 运行 `cd frontend && npm run dev` 验证开发服务器
- [ ] Step 3: 运行 `cd frontend && npm run build` 验证生产构建
- [ ] Step 4: 手动测试所有页面功能

**验证:** 
- `npm install` 成功
- `npm run dev` 启动成功
- `npm run build` 编译成功
- 所有页面功能正常

---

## 依赖关系图

```
Phase 1 (基础设施)
    ↓
Phase 2 (统一布局)
    ↓
Phase 3 (项目级组件)
    ↓
Phase 4-8 (页面重构) ← 可并行执行
    ↓
Phase 9 (清理验证)
```

## 并行执行机会

1. **Phase 4-8 可并行执行**：各页面重构相互独立
2. **Task 3.1-3.8 可并行创建**：项目级组件相互独立
3. **Task 5.1-5.3 可并行执行**：题库管理页面重构相互独立

## 风险区域与缓解策略

### 风险 1: shadcn-vue 组件安装失败
**缓解**: 检查 `components.json` 配置，确保 `typescript: false`，手动安装依赖

### 风险 2: 样式冲突
**缓解**: 使用 CSS 变量隔离样式，避免全局样式污染

### 风险 3: 组件引用断裂
**缓解**: 重构前检查组件引用，使用 IDE 的查找引用功能

### 风险 4: 业务逻辑被意外修改
**缓解**: 重构时只修改模板和样式，不修改 `<script>` 中的业务逻辑

### 风险 5: TypeScript 编译错误
**缓解**: 确保 `components.json` 中 `typescript: false`，手动检查 utils.js

---

## 时间估算

| Phase | 任务数 | 预计时间 |
|-------|--------|----------|
| Phase 1 | 3 | 1-2 小时 |
| Phase 2 | 4 | 2-3 小时 |
| Phase 3 | 8 | 3-4 小时 |
| Phase 4 | 2 | 1-2 小时 |
| Phase 5 | 3 | 2-3 小时 |
| Phase 6 | 3 | 2-3 小时 |
| Phase 7 | 4 | 2-3 小时 |
| Phase 8 | 9 | 2-3 小时 |
| Phase 9 | 3 | 1-2 小时 |
| **总计** | **39** | **16-23 小时** |

---

## 关键组件分析

### App.vue 结构
- **Tab 切换**：使用 `activeTab` ref 控制当前 Tab
- **侧边栏**：`SidebarProvider` + `AppSidebar` + `SidebarInset`
- **头部**：`SiteHeader`（面包屑、搜索、设置）
- **内容区**：根据 `activeTab` 显示不同组件

### AppSidebar.vue 结构
- **Logo 区域**：InterviewBoss 品牌标识
- **导航菜单**：`SidebarMenu` + `SidebarMenuItem`
- **分析面板**：`AnalyticsSidebar`
- **用户菜单**：`UserMenu`

### SiteHeader.vue 结构
- **面包屑**：Dashboard / 当前页面
- **搜索框**：搜索 ⌘K
- **设置按钮**：系统配置
- **暗色模式切换**：主题切换

### 业务组件清单
| 组件 | 用途 | 优先级 |
|------|------|--------|
| LoginPage | 登录页面 | 高 |
| MasterBankList | 题库列表 | 高 |
| PracticePanel | 练习面板 | 高 |
| MockInterview | 模拟面试 | 高 |
| ChatView | 对话视图 | 中 |
| CodingPractice | 代码练习 | 中 |
| SettingsPanel | 设置面板 | 中 |
| ProfilePanel | 个人资料 | 低 |
| AnalyticsSidebar | 分析侧边栏 | 低 |
| KnowledgeGraph | 知识图谱 | 低 |

---

## 执行建议

### 优先级排序
1. **Phase 1**（基础设施）→ 必须首先完成
2. **Phase 3**（项目级组件）→ 必须在页面重构前完成
3. **Phase 2**（统一布局）→ 可以与 Phase 3 并行
4. **Phase 4-8**（页面重构）→ 可以并行执行
5. **Phase 9**（清理验证）→ 最后完成

### 并行执行策略
- **Task 3.1-3.8**：可以同时创建所有项目级组件
- **Task 4.1-8.9**：各页面重构相互独立，可以并行执行
- **Task 9.1-9.3**：清理和验证可以并行执行

### 验证策略
- 每个 Task 完成后运行 `npm run dev` 验证
- 每个 Phase 完成后运行 `npm run build` 验证
- Phase 9 完成后运行完整验证流程

### 回滚策略
- 如果某个 Task 失败，可以回滚到上一个稳定状态
- 使用 Git 分支管理，每个 Phase 创建一个分支
- Phase 9 完成后合并到 main 分支

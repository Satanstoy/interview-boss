# shadcn-vue 全盘迁移实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将前端所有自定义 UI 组件替换为 shadcn-vue 组件，统一视觉风格

**Architecture:** 自底向上分 6 批迁移：先清理 CSS 原语 → Dialog/Modal → 表单控件 → 数据展示 → 状态/布局 → 业务组件。每批 commit，每步 build 验证。

**Tech Stack:** Vue 3 / shadcn-vue 2.7.3 / reka-ui / Tailwind CSS / class-variance-authority

---

## 文件结构

### 新增
- `src/components/ui/alert-dialog/` — 由 `npx shadcn-vue add alert-dialog` 自动生成

### 修改（按批次）
- **第 1 批**：`src/assets/styles/global.css` + 所有使用 `btn-primary`/`btn-secondary`/`btn-ghost`/`badge`/`card-smooth` 的文件（约 15 个）
- **第 2 批**：`src/components/common/AppDialog.vue`（重写）、`BaseModal.vue`（删除）、`ConfirmDialog.vue`（重写）+ 引用它们的文件
- **第 3 批**：`RoundedSelect.vue`（删除）、`AppSearchForm.vue`（重写）、`InlineEdit.vue`（重写）+ 引用 RoundedSelect 的文件
- **第 4 批**：`AppTable.vue`（重写）、`DataTable.vue`（重写）、`PaginationBar.vue`（重写）
- **第 5 批**：`AppLoading.vue`（重写）、`AsyncLoading.vue`（重写）、`AppCard.vue`（重写）、`BatchActionPanel.vue`（重写）
- **第 6 批**：`src/components/business/` 下各组件

---

## Task 0: 前置准备

**Files:**
- Create: `src/components/ui/alert-dialog/` (auto-generated)

- [ ] **Step 1: 安装 alert-dialog 组件**

```bash
cd frontend && npx shadcn-vue add alert-dialog
```

- [ ] **Step 2: 确认构建通过**

```bash
cd frontend && npm run build
```

Expected: 构建成功，无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/alert-dialog/
git commit -m "feat(frontend): add shadcn alert-dialog component"
```

---

## Task 1: 清理 global.css 中的自定义组件类

**Files:**
- Modify: `src/assets/styles/global.css:82-113`

- [ ] **Step 1: 删除 btn-primary、btn-secondary、btn-ghost、badge、card-smooth 类**

从 `global.css` 的 `@layer components` 块中删除以下类（第 82-113 行区域）：
- `.btn-primary` 及其 `:hover`、`:active` 伪类
- `.btn-secondary` 及其 `:active` 伪类
- `.btn-ghost` 及其 `:active` 伪类
- `.badge`
- `.card-smooth` 及其 `.dark`、`:hover` 伪类

保留 `@layer components` 中的其他类（skeleton、custom-scrollbar、prose-chat 等）。

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建失败（因为引用这些类的文件还存在），这是预期的——后续任务会逐一修复。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/assets/styles/global.css
git commit -m "refactor(frontend): remove custom btn/badge/card CSS classes from global.css"
```

---

## Task 2: 替换 App.vue 中的 CSS 类

**Files:**
- Modify: `frontend/src/App.vue:123,207,210,213,216`

- [ ] **Step 1: 替换 card-smooth（第 123 行）**

将：
```html
<div v-for="(w, i) in skeletonCards" :key="i" class="card-smooth p-5 space-y-3">
```
替换为：
```html
<Card v-for="(w, i) in skeletonCards" :key="i" class="p-5">
```

在 `<script setup>` 中添加 import：
```js
import { Card } from '@/components/ui/card'
```

- [ ] **Step 2: 替换 btn-primary（第 207、210 行）**

将：
```html
<button v-if="displayUser?.is_admin" @click="triggerBuildMasterBank" :disabled="isBuilding" class="btn-primary text-xs">
```
替换为：
```html
<Button v-if="displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildMasterBank" :disabled="isBuilding">
```

同理处理第 210 行的另一个 `btn-primary`。

在 `<script setup>` 中添加 import：
```js
import { Button } from '@/components/ui/button'
```

- [ ] **Step 3: 替换 btn-secondary（第 213、216 行）**

将：
```html
<button v-if="filteredMasterBank.length > 0" @click="enterPracticeMode" class="btn-secondary text-xs">
```
替换为：
```html
<Button v-if="filteredMasterBank.length > 0" variant="outline" size="sm" @click="enterPracticeMode">
```

同理处理第 216 行。

- [ ] **Step 4: 构建验证**

```bash
cd frontend && npm run build
```

Expected: App.vue 相关错误消除，但其他文件仍有错误

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.vue
git commit -m "refactor(frontend): replace custom CSS classes with shadcn components in App.vue"
```

---

## Task 3: 替换 QuestionCard.vue 中的 CSS 类

**Files:**
- Modify: `frontend/src/components/business/QuestionCard.vue`

- [ ] **Step 1: 添加 imports**

在 `<script setup>` 中添加：
```js
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
```

- [ ] **Step 2: 替换所有 badge 类**

将所有 `class="badge ..."` 的 `<span>` 替换为 `<Badge>` 组件。示例：

将：
```html
<span class="badge rounded-md bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">
```
替换为：
```html
<Badge variant="outline" class="rounded-md bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">
```

对 QuestionCard.vue 中所有 `class="badge"` 的 `<span>` 执行相同替换（约 8 处）。

- [ ] **Step 3: 替换所有 btn-ghost 类**

将：
```html
<button ... class="btn-ghost text-xs px-2 py-1 rounded-md ...">
```
替换为：
```html
<Button variant="ghost" size="sm" class="px-2 py-1 ...">
```

- [ ] **Step 4: 替换所有 btn-primary 类**

将 `class="btn-primary ..."` 替换为 `<Button variant="default" size="sm" ...>`。

- [ ] **Step 5: 替换所有 btn-secondary 类**

将 `class="btn-secondary ..."` 替换为 `<Button variant="outline" size="sm" ...>`。

- [ ] **Step 6: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/business/QuestionCard.vue
git commit -m "refactor(frontend): replace custom CSS classes with shadcn in QuestionCard.vue"
```

---

## Task 4: 替换 MockInterview.vue 中的 CSS 类

**Files:**
- Modify: `frontend/src/components/business/MockInterview.vue`

- [ ] **Step 1: 添加 imports**

```js
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
```

- [ ] **Step 2: 替换所有 btn-primary/btn-secondary/btn-ghost（约 6 处）**

按 Task 2-3 中的映射规则替换：
- `btn-primary` → `<Button variant="default">`
- `btn-secondary` → `<Button variant="outline">`
- `btn-ghost` → `<Button variant="ghost">`

注意保留原有的 `text-xs`、`px-4 py-1.5` 等 size 相关 class，或映射到 shadcn size。

- [ ] **Step 3: 替换 badge 类（2 处）**

将 `class="badge ..."` 替换为 `<Badge>`。

- [ ] **Step 4: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/business/MockInterview.vue
git commit -m "refactor(frontend): replace custom CSS classes with shadcn in MockInterview.vue"
```

---

## Task 5: 替换剩余 business 组件中的 CSS 类

**Files:**
- Modify: `frontend/src/components/business/PracticePanel.vue:13-14,44`
- Modify: `frontend/src/components/business/PracticeMode.vue:11,15,58,62`
- Modify: `frontend/src/components/business/AnalyticsSidebar.vue:52`
- Modify: `frontend/src/components/business/AdminReview.vue:54-56,79`
- Modify: `frontend/src/components/business/MasterBankList.vue:12-13,25`
- Modify: `frontend/src/components/business/MergeQuestionDialog.vue:27,46`
- Modify: `frontend/src/components/business/ProfilePanel.vue:75,78,248`
- Modify: `frontend/src/components/common/BatchActionPanel.vue:3,7`

- [ ] **Step 1: 逐文件替换 btn-primary/btn-secondary/btn-ghost**

按以下文件顺序处理，每个文件：
1. 添加 `import { Button } from '@/components/ui/button'`
2. 替换所有 `btn-primary` → `<Button variant="default">`
3. 替换所有 `btn-secondary` → `<Button variant="outline">`
4. 替换所有 `btn-ghost` → `<Button variant="ghost">`

文件列表：
- `PracticePanel.vue` — 无 btn 类（只有 badge）
- `AnalyticsSidebar.vue` — 1 处 btn-secondary
- `AdminReview.vue` — 1 处 btn-ghost
- `MasterBankList.vue` — 2 处 btn-ghost + 1 处 btn-primary
- `MergeQuestionDialog.vue` — 1 处 btn-primary + 1 处 btn-secondary
- `ProfilePanel.vue` — 1 处 btn-primary + 2 处 btn-secondary
- `BatchActionPanel.vue` — 2 处 btn-ghost

- [ ] **Step 2: 逐文件替换 badge 类**

对以下文件中的 `class="badge ..."` 替换为 `<Badge>`：
- `PracticePanel.vue` — 3 处
- `PracticeMode.vue` — 4 处
- `AdminReview.vue` — 3 处

每个文件添加 `import { Badge } from '@/components/ui/badge'`。

- [ ] **Step 3: 构建验证**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/
git commit -m "refactor(frontend): replace remaining btn/badge CSS classes across business components"
```

---

## Task 6: 重写 AppDialog.vue 使用 shadcn Dialog

**Files:**
- Rewrite: `frontend/src/components/common/AppDialog.vue`

- [ ] **Step 1: 重写 AppDialog.vue**

新内容：
```vue
<template>
  <Dialog :open="open" @update:open="$emit('update:open', $event)">
    <DialogContent :class="maxWidthClass" :show-close-button="showCloseButton">
      <DialogHeader v-if="title || description || $slots.header">
        <slot name="header">
          <DialogTitle v-if="title">{{ title }}</DialogTitle>
          <DialogDescription v-if="description">{{ description }}</DialogDescription>
        </slot>
      </DialogHeader>

      <slot />

      <DialogFooter v-if="$slots.footer">
        <slot name="footer" />
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  maxWidth: { type: String, default: '' },
  size: { type: String, default: 'md' },
  showCloseButton: { type: Boolean, default: true },
  closeOnBackdrop: { type: Boolean, default: true },
})

defineEmits(['update:open'])

const sizeMap = {
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-lg',
  lg: 'sm:max-w-2xl',
  xl: 'sm:max-w-4xl',
  full: 'sm:max-w-[90vw]',
}

const maxWidthClass = computed(() => {
  if (props.maxWidth) return props.maxWidth
  return sizeMap[props.size] || 'sm:max-w-lg'
})
</script>
```

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/common/AppDialog.vue
git commit -m "refactor(frontend): rewrite AppDialog to use shadcn Dialog"
```

---

## Task 7: 重写 ConfirmDialog.vue 使用 shadcn AlertDialog

**Files:**
- Rewrite: `frontend/src/components/common/ConfirmDialog.vue`

- [ ] **Step 1: 重写 ConfirmDialog.vue**

新内容：
```vue
<template>
  <AlertDialog :open="confirmState.show" @update:open="handleCancel">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{{ confirmState.title }}</AlertDialogTitle>
        <AlertDialogDescription class="whitespace-pre-line">
          {{ confirmState.message }}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel @click="handleCancel">
          {{ confirmState.cancelLabel || '取消' }}
        </AlertDialogCancel>
        <AlertDialogAction :class="confirmBtnClass" @click="handleConfirm">
          {{ confirmState.confirmLabel || '确定' }}
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>

<script setup>
import { computed } from 'vue'
import { useConfirm } from '@/composables/useNotification.js'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

const { confirmState, handleConfirm, handleCancel } = useConfirm()

const variant = computed(() => confirmState.value.variant || 'warning')

const confirmBtnClass = computed(() => ({
  danger: 'bg-destructive text-white hover:bg-destructive/90',
  warning: '',
  info: 'bg-blue-600 text-white hover:bg-blue-700',
}[variant.value]))
</script>
```

注意：需要确认 `alert-dialog` 组件的导出路径。安装后检查 `src/components/ui/alert-dialog/index.js` 或 `index.ts` 的导出。

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/common/ConfirmDialog.vue
git commit -m "refactor(frontend): rewrite ConfirmDialog to use shadcn AlertDialog"
```

---

## Task 8: 删除 BaseModal.vue 并迁移引用

**Files:**
- Delete: `frontend/src/components/common/BaseModal.vue`
- Modify: `frontend/src/components/business/NewChatModal.vue:2,115,123`

- [ ] **Step 1: 修改 NewChatModal.vue**

将 BaseModal 替换为 AppDialog：

在 `<script setup>` 中：
- 删除 `import BaseModal from '@/components/common/BaseModal.vue'`
- 添加 `import AppDialog from '@/components/common/AppDialog.vue'`

在模板中，将：
```html
<BaseModal :visible="visible" size="md" @close="emit('close')">
  ...
</BaseModal>
```
替换为：
```html
<AppDialog :open="visible" size="md" @update:open="emit('close')">
  ...
</AppDialog>
```

- [ ] **Step 2: 删除 BaseModal.vue**

```bash
rm frontend/src/components/common/BaseModal.vue
```

- [ ] **Step 3: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add -A frontend/src/components/
git commit -m "refactor(frontend): remove BaseModal, migrate NewChatModal to AppDialog"
```

---

## Task 9: 删除 RoundedSelect.vue 并迁移引用

**Files:**
- Delete: `frontend/src/components/common/RoundedSelect.vue`
- Modify: `frontend/src/App.vue:276,487`
- Modify: `frontend/src/components/business/StagingPanel.vue:82,95,105,211`
- Modify: `frontend/src/components/business/NewChatModal.vue:49,122`
- Modify: `frontend/src/components/business/SearchFilterBar.vue:30,49`
- Modify: `frontend/src/components/common/InlineEdit.vue:19,41`
- Modify: `frontend/src/components/common/PaginationBar.vue:46,60`

- [ ] **Step 1: 确认 shadcn Select 的导出**

检查 `src/components/ui/select/index.js` 或 `index.ts`，确认 Select、SelectTrigger、SelectValue、SelectContent、SelectItem 等组件的导出。

- [ ] **Step 2: 逐文件替换 RoundedSelect**

每个文件的替换模式：

将：
```html
<RoundedSelect
  :model-value="someValue"
  @update:model-value="someValue = $event"
  :options="[{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]"
  size="sm"
/>
```
替换为：
```html
<Select :model-value="String(someValue)" @update:model-value="someValue = Number($event) || $event">
  <SelectTrigger class="h-8 text-xs">
    <SelectValue />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="a">A</SelectItem>
    <SelectItem value="b">B</SelectItem>
  </SelectContent>
</Select>
```

添加 import：
```js
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
```

注意：RoundedSelect 的 `options: [{value, label}]` API 需要展开为 `<SelectItem>` 子组件。如果 value 是 Number 类型，shadcn Select 要求 String，需要做转换。

逐个处理以下文件（按依赖顺序）：
1. `PaginationBar.vue` — 1 处（pageSize 选择器）
2. `InlineEdit.vue` — 1 处（select 类型编辑）
3. `SearchFilterBar.vue` — 1 处
4. `NewChatModal.vue` — 1 处
5. `StagingPanel.vue` — 3 处
6. `App.vue` — 1 处

- [ ] **Step 3: 删除 RoundedSelect.vue**

```bash
rm frontend/src/components/common/RoundedSelect.vue
```

- [ ] **Step 4: 构建验证**

```bash
cd frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(frontend): remove RoundedSelect, migrate all refs to shadcn Select"
```

---

## Task 10: 重写 AppSearchForm.vue 使用 shadcn Input

**Files:**
- Rewrite: `frontend/src/components/common/AppSearchForm.vue`

- [ ] **Step 1: 重写 AppSearchForm.vue**

新内容：
```vue
<template>
  <div class="flex flex-col sm:flex-row gap-3">
    <div class="relative flex-1">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
      <Input
        :model-value="modelValue"
        type="text"
        :placeholder="placeholder"
        class="pl-9 pr-9"
        @update:model-value="$emit('update:modelValue', $event)"
        @keydown.enter="$emit('search')"
      />
      <button
        v-if="modelValue"
        type="button"
        class="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
        @click="$emit('update:modelValue', ''); $emit('reset')"
      >
        <X class="h-4 w-4" />
      </button>
    </div>

    <div v-if="$slots.filters" class="flex items-center gap-2 flex-wrap">
      <slot name="filters" />
    </div>

    <div v-if="showButtons" class="flex items-center gap-2 shrink-0">
      <Button variant="outline" size="sm" @click="$emit('reset')">
        <RotateCcw class="w-3.5 h-3.5" />
        重置
      </Button>
      <Button size="sm" @click="$emit('search')">
        <Search class="w-4 h-4" />
        搜索
      </Button>
    </div>
  </div>
</template>

<script setup>
import { Search, X, RotateCcw } from '@lucide/vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '搜索...' },
  showButtons: { type: Boolean, default: true },
})

defineEmits(['update:modelValue', 'search', 'reset'])
</script>
```

注意：项目使用 `@lucide/vue`（已在 package.json 中），不是 `lucide-vue-next`。

- [ ] **Step 2: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/AppSearchForm.vue
git commit -m "refactor(frontend): rewrite AppSearchForm to use shadcn Input + Button"
```

---

## Task 11: 重写 InlineEdit.vue 使用 shadcn Input + Select

**Files:**
- Rewrite: `frontend/src/components/common/InlineEdit.vue`

- [ ] **Step 1: 重写 InlineEdit.vue**

新内容：
```vue
<template>
  <div class="group">
    <!-- Display mode -->
    <div v-if="!editing" class="flex items-center gap-2">
      <span v-if="type === 'select'" class="px-2 py-1 rounded text-xs" :class="(displayValue || '').includes('难') ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400' : 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'">
        {{ displayValue || '-' }}
      </span>
      <span v-else :class="{ 'whitespace-pre-wrap break-words flex-1': type === 'textarea' }">{{ displayValue }}</span>
      <Button variant="ghost" size="icon-xs" class="opacity-0 group-hover:opacity-100 transition text-muted-foreground hover:text-blue-500" @click="startEdit" title="编辑">
        <Pencil class="w-3.5 h-3.5" />
      </Button>
    </div>

    <!-- Edit mode -->
    <div v-else class="flex flex-col gap-1 w-full">
      <div class="flex items-center gap-1">
        <Input v-if="type === 'text'" v-model="editValue" class="h-8 text-sm" @keyup.enter="save" />
        <Textarea v-else-if="type === 'textarea'" v-model="editValue" :rows="rows || 3" class="text-sm" />
        <Select v-else-if="type === 'select'" v-model="editValue">
          <SelectTrigger class="h-8 text-xs flex-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">未提供</SelectItem>
            <SelectItem v-for="opt in options" :key="opt" :value="opt">{{ opt }}</SelectItem>
          </SelectContent>
        </Select>
        <Input v-else v-model="editValue" class="h-8 text-sm" @keyup.enter="save" />
        <div class="flex gap-1 shrink-0">
          <Button variant="ghost" size="sm" class="text-green-500 hover:text-green-700" @click="save">保存</Button>
          <Button variant="ghost" size="sm" class="text-red-400 hover:text-red-600" @click="editing = false">取消</Button>
        </div>
      </div>
      <p v-if="validationError" class="text-red-500 dark:text-red-400 text-xs mt-0.5">{{ validationError }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Pencil } from '@lucide/vue'
import { validateTextField } from '@/utils/validate.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const props = defineProps({
  row: { type: Object, required: true },
  field: { type: String, required: true },
  dbColumn: { type: String, required: true },
  tableName: { type: String, required: true },
  type: { type: String, default: 'text' },
  rows: { type: Number, default: 3 },
  options: { type: Array, default: () => [] }
})

const emit = defineEmits(['save'])

const editing = ref(false)
const editValue = ref('')
const validationError = ref('')

const displayValue = computed(() => props.row[props.field])

const startEdit = () => {
  editValue.value = props.row[props.field] || ''
  validationError.value = ''
  editing.value = true
}

const save = () => {
  const result = validateTextField(editValue.value, props.field)
  if (!result.valid) {
    validationError.value = result.error
    return
  }
  validationError.value = ''
  emit('save', props.tableName, props.row.id, props.dbColumn, result.value, props.row, '_editing_inline', props.field)
  editing.value = false
}
</script>
```

- [ ] **Step 2: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/InlineEdit.vue
git commit -m "refactor(frontend): rewrite InlineEdit to use shadcn Input/Select/Button"
```

---

## Task 12: 重写 AppTable.vue 使用 shadcn Table

**Files:**
- Rewrite: `frontend/src/components/common/AppTable.vue`

- [ ] **Step 1: 重写 AppTable.vue**

新内容：
```vue
<template>
  <div class="w-full rounded-xl border border-border bg-card shadow-sm overflow-hidden">
    <!-- Loading overlay -->
    <div v-if="loading" class="relative">
      <div class="absolute inset-0 z-10 flex items-center justify-center bg-card/80 backdrop-blur-sm">
        <div class="flex items-center gap-2.5">
          <Loader2 class="animate-spin h-5 w-5 text-primary" />
          <span class="text-sm font-medium text-muted-foreground">加载中...</span>
        </div>
      </div>
    </div>

    <div class="w-full overflow-x-auto custom-scrollbar">
      <Table>
        <TableHeader>
          <TableRow class="bg-surface-50/50 dark:bg-ink-800/50">
            <TableHead
              v-for="col in columns"
              :key="col.key"
              class="whitespace-nowrap"
              :class="col.headerClass || ''"
              :style="col.width ? { width: col.width } : {}"
            >
              {{ col.label }}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <template v-if="rows.length > 0">
            <TableRow
              v-for="(row, idx) in rows"
              :key="rowKey ? row[rowKey] : idx"
              class="animate-fade-in"
              :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
            >
              <TableCell
                v-for="col in columns"
                :key="col.key"
                :class="col.cellClass || ''"
                :style="col.width ? { width: col.width } : {}"
              >
                <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
                  {{ row[col.frontendKey || col.key] }}
                </slot>
              </TableCell>
            </TableRow>
          </template>
          <TableEmpty v-else :colspan="columns.length">
            <div class="flex flex-col items-center py-8">
              <Inbox class="w-8 h-8 text-muted-foreground/50 mb-2" />
              <p class="text-sm font-medium text-muted-foreground">{{ emptyText }}</p>
              <p v-if="emptyDescription" class="text-xs text-muted-foreground/70 mt-1">{{ emptyDescription }}</p>
            </div>
          </TableEmpty>
        </TableBody>
      </Table>
    </div>
  </div>
</template>

<script setup>
import { Loader2, Inbox } from '@lucide/vue'
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无数据' },
  emptyDescription: { type: String, default: '' },
  rowKey: { type: String, default: 'id' },
})
</script>
```

- [ ] **Step 2: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/AppTable.vue
git commit -m "refactor(frontend): rewrite AppTable to use shadcn Table"
```

---

## Task 13: 重写 BatchActionPanel.vue 使用 shadcn Button

**Files:**
- Rewrite: `frontend/src/components/common/BatchActionPanel.vue`

- [ ] **Step 1: 重写 BatchActionPanel.vue**

新内容：
```vue
<template>
  <div class="mb-2 flex flex-wrap gap-2 items-center bg-card p-2 rounded-xl border border-border shadow-sm">
    <Button variant="ghost" size="sm" @click="$emit('toggle-select-all')">
      <CheckSquare class="w-3.5 h-3.5" />
      全选
    </Button>
    <Button variant="ghost" size="sm" @click="$emit('invert-selection')">
      <ArrowLeftRight class="w-3.5 h-3.5" />
      反选
    </Button>
    <div class="w-px h-5 bg-surface-200 dark:bg-ink-700 mx-1"></div>
    <Button
      v-for="action in actions" :key="action.key"
      variant="outline"
      size="sm"
      :disabled="selectedCount === 0 || action.disabled || runningAction !== null"
      class="text-xs"
      :class="colorClasses(action.color)"
      @click="executeAction(action)"
    >
      {{ action.label }}
      <span class="bg-white/30 dark:bg-white/10 px-1.5 py-0.5 rounded text-[10px] font-bold">{{ selectedCount }}</span>
    </Button>
    <div v-if="runningAction" class="flex items-center gap-2.5">
      <div class="w-32 h-1.5 bg-surface-200 dark:bg-ink-700 rounded-full overflow-hidden">
        <div
          class="h-full bg-gradient-brand rounded-full transition-all duration-300"
          :style="{ width: progressPct + '%' }"
        ></div>
      </div>
      <span class="text-xs text-ink-500 dark:text-ink-400 tabular-nums font-medium">{{ progress.current }}/{{ progress.total }}</span>
    </div>
    <slot />
    <div v-if="$slots.right" class="ml-auto flex items-center gap-2">
      <slot name="right" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { CheckSquare, ArrowLeftRight } from '@lucide/vue'
import { Button } from '@/components/ui/button'

defineProps({
  selectedCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 },
  actions: { type: Array, default: () => [] }
})

defineEmits(['toggle-select-all', 'invert-selection'])

const runningAction = ref(null)
const progress = ref({ current: 0, total: 0 })

const progressPct = computed(() => {
  if (!progress.value.total) return 0
  return Math.round((progress.value.current / progress.value.total) * 100)
})

const executeAction = async (action) => {
  if (runningAction.value) return
  runningAction.value = action.key
  progress.value = { current: 0, total: 0 }
  try {
    await action.handler((current, total) => {
      progress.value = { current, total }
    })
  } catch (e) {
    console.error(`Batch action ${action.key} failed:`, e)
  } finally {
    setTimeout(() => {
      runningAction.value = null
      progress.value = { current: 0, total: 0 }
    }, 1500)
  }
}

const colorClasses = (color) => {
  const map = {
    red: 'text-red-700 dark:text-red-400 border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/30',
    blue: 'text-primary-700 dark:text-primary-400 border-primary-200 dark:border-primary-800 bg-primary-50 dark:bg-primary-900/30',
    green: 'text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/30',
    yellow: 'text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/30',
  }
  return map[color] || map.blue
}
</script>
```

- [ ] **Step 2: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/BatchActionPanel.vue
git commit -m "refactor(frontend): rewrite BatchActionPanel to use shadcn Button"
```

---

## Task 14: 重写 DataTable.vue 使用 shadcn Table

**Files:**
- Rewrite: `frontend/src/components/common/DataTable.vue`

- [ ] **Step 1: 重写 DataTable.vue**

将内部的 `<table>` 替换为 shadcn Table 组件，保留 BatchActionPanel 和 PaginationBar 的引用。内部 `<input type="checkbox">` 替换为 shadcn Checkbox（如有安装）或保留原生。

```vue
<template>
  <div class="w-full">
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="rows.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    />

    <div class="rounded-xl border border-border bg-card overflow-x-auto custom-scrollbar shadow-sm">
      <Table>
        <TableHeader>
          <TableRow class="bg-card text-xs">
            <TableHead class="w-10 text-center font-medium">选择</TableHead>
            <TableHead v-for="col in columns" :key="col.key" :class="col.class || ''" :style="col.width ? { width: col.width } : {}">
              {{ col.label }}
            </TableHead>
            <TableHead class="w-[100px] text-center font-medium">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody v-auto-animate>
          <TableRow v-for="(row, idx) in paginatedRows" :key="row.id"
            :data-row-id="row.id"
            class="animate-fade-in"
            :class="[
              highlightId != null && highlightId == row.id ? 'highlight-row' : '',
              isSelected(row.id) ? 'bg-surface-100/80 dark:bg-ink-800/70' : ''
            ]"
            :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
          >
            <TableCell class="text-center">
              <input type="checkbox" :checked="isSelected(row.id)" @change="$emit('toggle-item', row.id)"
                class="w-4 h-4 text-primary-600 rounded-md border-surface-300 dark:border-ink-600 focus:ring-primary-500 cursor-pointer transition">
            </TableCell>
            <TableCell v-for="col in columns" :key="col.key" :class="col.cellClass || ''" :style="col.width ? { width: col.width } : {}">
              <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
                {{ row[col.frontendKey || col.key] }}
              </slot>
            </TableCell>
            <TableCell class="text-center">
              <slot name="actions" :row="row" />
            </TableCell>
          </TableRow>
          <TableRow v-if="rows.length === 0">
            <TableCell :colspan="columns.length + 2" class="p-16 text-center">
              <div class="flex flex-col items-center">
                <Inbox class="w-8 h-8 text-muted-foreground/50 mb-2" />
                <p class="text-muted-foreground font-medium mb-1">暂无数据</p>
                <p class="text-sm text-muted-foreground/70">试试切换筛选条件或录入更多内容</p>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <PaginationBar
      :current-page="currentPage"
      :page-size="pageSize"
      :total="rows.length"
      @update:current-page="$emit('update:currentPage', $event)"
      @update:page-size="$emit('update:pageSize', $event)"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Inbox } from '@lucide/vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import BatchActionPanel from '@/components/common/BatchActionPanel.vue'
import PaginationBar from '@/components/common/PaginationBar.vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false },
  batchActions: { type: Array, default: () => [] },
  currentPage: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  highlightId: { type: Number, default: null }
})
defineEmits(['toggle-select-all', 'invert-selection', 'toggle-item', 'update:currentPage', 'update:pageSize'])

const paginatedRows = computed(() => {
  const start = (props.currentPage - 1) * props.pageSize
  return props.rows.slice(start, start + props.pageSize)
})
</script>

<style scoped>
.highlight-row {
  animation: highlight-pulse 4s ease-out forwards;
}
@keyframes highlight-pulse {
  0%, 30% { background-color: rgba(248, 221, 165, 0.5); }
  100% { background-color: transparent; }
}
:global(.dark) .highlight-row {
  animation: highlight-pulse-dark 4s ease-out forwards;
}
@keyframes highlight-pulse-dark {
  0%, 30% { background-color: rgba(248, 221, 165, 0.2); }
  100% { background-color: transparent; }
}
</style>
```

- [ ] **Step 2: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/DataTable.vue
git commit -m "refactor(frontend): rewrite DataTable to use shadcn Table"
```

---

## Task 15: 重写 PaginationBar.vue 使用 shadcn Button + Select

**Files:**
- Rewrite: `frontend/src/components/common/PaginationBar.vue`

- [ ] **Step 1: 重写 PaginationBar.vue**

```vue
<template>
  <div v-if="totalPages > 1" class="flex items-center justify-between gap-3 mt-4 px-1">
    <div class="text-xs text-muted-foreground tabular-nums">
      共 {{ total }} 条，第 {{ currentPage }}/{{ totalPages }} 页
    </div>

    <div class="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon-sm"
        :disabled="currentPage <= 1"
        @click="go(currentPage - 1)"
      >
        <ChevronLeft class="w-4 h-4" />
      </Button>

      <template v-for="p in visiblePages" :key="p">
        <span v-if="p === '...'" class="px-1 text-muted-foreground text-sm select-none">...</span>
        <Button
          v-else
          :variant="p === currentPage ? 'default' : 'outline'"
          size="sm"
          class="min-w-[32px] text-xs tabular-nums"
          @click="go(p)"
        >
          {{ p }}
        </Button>
      </template>

      <Button
        variant="outline"
        size="icon-sm"
        :disabled="currentPage >= totalPages"
        @click="go(currentPage + 1)"
      >
        <ChevronRight class="w-4 h-4" />
      </Button>
    </div>

    <div class="flex items-center gap-2 text-xs text-muted-foreground">
      <span>每页</span>
      <Select :model-value="String(pageSize)" @update:model-value="$emit('update:pageSize', Number($event)); $emit('update:currentPage', 1)">
        <SelectTrigger class="h-8 min-w-[60px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="s in pageSizeOptions" :key="s" :value="String(s)">{{ s }}</SelectItem>
        </SelectContent>
      </Select>
      <span>条</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const props = defineProps({
  currentPage: { type: Number, required: true },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, required: true },
  pageSizeOptions: { type: Array, default: () => [10, 20, 50, 100] }
})

const emit = defineEmits(['update:currentPage', 'update:pageSize'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const visiblePages = computed(() => {
  const pages = []
  const cur = props.currentPage
  const last = totalPages.value

  if (last <= 7) {
    for (let i = 1; i <= last; i++) pages.push(i)
    return pages
  }

  pages.push(1)
  if (cur > 3) pages.push('...')

  const start = Math.max(2, cur - 1)
  const end = Math.min(last - 1, cur + 1)
  for (let i = start; i <= end; i++) pages.push(i)

  if (cur < last - 2) pages.push('...')
  pages.push(last)

  return pages
})

const go = (page) => {
  if (page < 1 || page > totalPages.value) return
  emit('update:currentPage', page)
}
</script>
```

- [ ] **Step 2: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/PaginationBar.vue
git commit -m "refactor(frontend): rewrite PaginationBar to use shadcn Button + Select"
```

---

## Task 16: 重写 AppLoading.vue 和 AsyncLoading.vue

**Files:**
- Rewrite: `frontend/src/components/common/AppLoading.vue`
- Rewrite: `frontend/src/components/common/AsyncLoading.vue`

- [ ] **Step 1: 重写 AppLoading.vue**

将 skeleton 类型的 loading 改用 shadcn Skeleton 组件：

```vue
<template>
  <!-- Spinner type -->
  <div v-if="type === 'spinner'" class="flex items-center justify-center" :class="wrapperClass">
    <div class="flex items-center gap-2.5">
      <Loader2 class="animate-spin h-5 w-5 text-primary" />
      <span v-if="text" class="text-sm font-medium text-muted-foreground">{{ text }}</span>
    </div>
  </div>

  <!-- Full page loading -->
  <div v-else-if="type === 'page'" class="flex flex-col items-center justify-center py-20">
    <div class="relative">
      <div class="w-12 h-12 rounded-full border-4 border-surface-200 dark:border-ink-700" />
      <div class="absolute top-0 left-0 w-12 h-12 rounded-full border-4 border-transparent border-t-primary animate-spin" />
    </div>
    <p v-if="text" class="mt-4 text-sm font-medium text-muted-foreground">{{ text }}</p>
  </div>

  <!-- Skeleton rows -->
  <div v-else-if="type === 'skeleton'" class="space-y-3" :class="wrapperClass">
    <Skeleton v-for="i in rows" :key="i" :class="rowClass" :style="{ animationDelay: (i - 1) * 100 + 'ms' }" />
  </div>

  <!-- Skeleton cards -->
  <div v-else-if="type === 'cards'" class="grid gap-4" :class="gridClass">
    <div v-for="i in rows" :key="i" class="rounded-xl border border-surface-200 dark:border-ink-800 bg-card p-4 space-y-3">
      <div class="flex items-center gap-3">
        <Skeleton class="w-10 h-10 rounded-lg shrink-0" />
        <div class="flex-1 space-y-2">
          <Skeleton class="h-4 w-3/4" />
          <Skeleton class="h-3 w-1/2" />
        </div>
      </div>
      <div class="space-y-2">
        <Skeleton class="h-3 w-full" />
        <Skeleton class="h-3 w-5/6" />
      </div>
    </div>
  </div>

  <!-- Skeleton table -->
  <div v-else-if="type === 'table'" class="rounded-xl border border-border bg-card overflow-hidden">
    <div class="flex border-b border-border bg-surface-50/50 dark:bg-ink-800/50">
      <div v-for="i in 5" :key="i" class="flex-1 px-4 py-3">
        <Skeleton class="h-3 w-3/4" />
      </div>
    </div>
    <div v-for="i in rows" :key="i" class="flex border-b border-border/50 last:border-0">
      <div v-for="j in 5" :key="j" class="flex-1 px-4 py-3">
        <Skeleton class="h-3" :style="{ width: (40 + j * 10) + '%' }" />
      </div>
    </div>
  </div>

  <!-- Default: inline dots -->
  <div v-else class="flex items-center gap-1.5" :class="wrapperClass">
    <div class="w-2 h-2 rounded-full bg-primary animate-bounce" style="animation-delay: 0ms" />
    <div class="w-2 h-2 rounded-full bg-primary animate-bounce" style="animation-delay: 150ms" />
    <div class="w-2 h-2 rounded-full bg-primary animate-bounce" style="animation-delay: 300ms" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Loader2 } from '@lucide/vue'
import { Skeleton } from '@/components/ui/skeleton'

const props = defineProps({
  type: { type: String, default: 'spinner' },
  text: { type: String, default: '' },
  rows: { type: Number, default: 3 },
  gridCols: { type: Number, default: 3 },
  rowClass: { type: String, default: 'h-12 rounded-lg' },
  wrapperClass: { type: String, default: '' },
})

const gridClass = computed(() => {
  const cols = props.gridCols
  if (cols <= 1) return 'grid-cols-1'
  if (cols <= 2) return 'grid-cols-1 sm:grid-cols-2'
  if (cols <= 3) return 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'
  return 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4'
})
</script>
```

- [ ] **Step 2: 重写 AsyncLoading.vue**

```vue
<template>
  <div class="flex items-center justify-center min-h-[200px]">
    <div class="flex flex-col items-center gap-3">
      <Loader2 class="w-8 h-8 text-primary animate-spin" />
      <p class="text-sm text-muted-foreground">加载中...</p>
    </div>
  </div>
</template>

<script setup>
import { Loader2 } from '@lucide/vue'
</script>
```

- [ ] **Step 3: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/AppLoading.vue frontend/src/components/common/AsyncLoading.vue
git commit -m "refactor(frontend): rewrite AppLoading/AsyncLoading to use shadcn Skeleton"
```

---

## Task 17: 重写 AppCard.vue 使用 shadcn Card

**Files:**
- Rewrite: `frontend/src/components/common/AppCard.vue`

- [ ] **Step 1: 重写 AppCard.vue**

```vue
<template>
  <Card
    :class="cn(
      hover && 'hover:border-surface-300 dark:hover:border-ink-700 hover:shadow-md transition-shadow',
      props.class
    )"
  >
    <CardHeader v-if="title || $slots.header || $slots['card-title']" class="flex-row items-start justify-between gap-4">
      <div class="min-w-0 flex-1 space-y-1.5">
        <slot name="header">
          <CardTitle v-if="title">
            <slot name="card-title">{{ title }}</slot>
          </CardTitle>
          <CardDescription v-if="description">
            {{ description }}
          </CardDescription>
        </slot>
      </div>
      <div v-if="$slots['card-action']" class="shrink-0">
        <slot name="card-action" />
      </div>
    </CardHeader>

    <CardContent :class="cn(noPadding && 'p-0')">
      <slot />
    </CardContent>

    <CardFooter v-if="$slots.footer">
      <slot name="footer" />
    </CardFooter>
  </Card>
</template>

<script setup>
import { cn } from '@/lib/utils'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

const props = defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  noPadding: { type: Boolean, default: false },
  hover: { type: Boolean, default: false },
  class: { type: [String, Object, Array], default: '' },
})
</script>
```

- [ ] **Step 2: 构建验证 + Commit**

```bash
cd frontend && npm run build
git add frontend/src/components/common/AppCard.vue
git commit -m "refactor(frontend): rewrite AppCard to use shadcn Card"
```

---

## Task 18: 清理 global.css 中的废弃样式

**Files:**
- Modify: `frontend/src/assets/styles/global.css`

- [ ] **Step 1: 删除 .skeleton 类**

如果所有 skeleton 使用已改为 shadcn Skeleton，从 global.css 中删除 `.skeleton` 类定义（约第 15-20 行）。

- [ ] **Step 2: 删除 .empty-state 相关类**

删除 `.empty-state`、`.empty-state-icon`、`.empty-state-title`、`.empty-state-desc`（如果已不再使用）。

- [ ] **Step 3: 构建验证**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/assets/styles/global.css
git commit -m "refactor(frontend): clean up unused CSS classes from global.css"
```

---

## Task 19: 最终构建验证 + 前端 CLAUDE.md 更新

**Files:**
- Modify: `frontend/CLAUDE.md`

- [ ] **Step 1: 全量构建验证**

```bash
cd frontend && npm run build
```

Expected: 构建成功，无错误

- [ ] **Step 2: 更新 frontend/CLAUDE.md**

在 UI 方向部分更新：
```markdown
## UI 方向

- 全面采用 shadcn-vue 组件（reka-vega 风格），禁止手写自定义 UI 组件类
- Button/Card/Badge/Dialog/Select/Table 等一律使用 shadcn 组件，不使用自定义 CSS 类
- global.css 仅保留全局基础样式（reset、scrollbar、prose-chat、elevation），不包含组件样式
```

- [ ] **Step 3: Commit**

```bash
git add frontend/CLAUDE.md
git commit -m "docs(frontend): update CLAUDE.md to reflect shadcn-vue migration"
```

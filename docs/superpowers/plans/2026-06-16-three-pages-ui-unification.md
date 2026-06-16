# 三页面 UI 统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将高频题库、JD库、面经库三个页面的 UI 统一到 shadcn-vue 官方组件体系

**Architecture:** 安装 shadcn accordion/pagination/empty 组件 → 升级 DataTable 内部分页 → 统一 JD/Interview 页头 → 重构 MasterBank 为 Accordion 布局 → 统一筛选栏和空状态

**Tech Stack:** Vue 3 Composition API, shadcn-vue, Tailwind CSS, @lucide/vue

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `components/ui/accordion/` | Install | shadcn Accordion 组件 |
| `components/ui/pagination/` | Install | shadcn Pagination 组件 |
| `components/ui/empty/` | Install | shadcn Empty 组件 |
| `components/common/DataTable.vue` | Modify | 替换 PaginationBar → shadcn Pagination + Empty |
| `components/common/PaginationBar.vue` | Delete | 被 shadcn Pagination 替代 |
| `components/common/AppEmpty.vue` | Delete | 被 shadcn Empty 替代 |
| `views/JdView.vue` | Modify | 添加统一页头 Card |
| `views/InterviewView.vue` | Modify | 添加统一页头 Card |
| `views/MasterBankView.vue` | Modify | 统一筛选栏样式 |
| `components/business/MasterBankList.vue` | Modify | 替换为 Accordion + Empty |
| `components/business/QuestionCard.vue` | Modify | 适配 AccordionTrigger/Content 结构 |

---

### Task 1: 安装 shadcn 组件

**Files:**
- Create: `components/ui/accordion/` (shadcn CLI)
- Create: `components/ui/pagination/` (shadcn CLI)
- Create: `components/ui/empty/` (shadcn CLI)

- [ ] **Step 1: 安装 accordion**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npx shadcn-vue@latest add accordion --yes
```

Expected: `components/ui/accordion/` 目录创建，包含 Accordion.vue, AccordionContent.vue, AccordionItem.vue, AccordionTrigger.vue, index.ts

- [ ] **Step 2: 安装 pagination**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npx shadcn-vue@latest add pagination --yes
```

Expected: `components/ui/pagination/` 目录创建

- [ ] **Step 3: 安装 empty**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npx shadcn-vue@latest add empty --yes
```

Expected: `components/ui/empty/` 目录创建

- [ ] **Step 4: 验证构建**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build 2>&1 | tail -5
```

Expected: `✓ built in` 无报错

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/sj/interview-boss && git add frontend/src/components/ui/accordion/ frontend/src/components/ui/pagination/ frontend/src/components/ui/empty/ && git commit -m "chore(frontend): install shadcn accordion, pagination, empty components"
```

---

### Task 2: 升级 DataTable 分页为 shadcn Pagination

**Files:**
- Modify: `components/common/DataTable.vue:58-64` — 替换 PaginationBar 为 shadcn Pagination
- Modify: `components/common/DataTable.vue:68-73` — 更新 imports

这一步只改 DataTable 内部的分页组件，保持 props 和 emits 接口不变，JD 和 Interview 无需改动即可生效。

- [ ] **Step 1: 重写 DataTable.vue**

将 `DataTable.vue` 的 template 中 `<PaginationBar ... />` 替换为 shadcn Pagination，script 中替换 import。

完整新文件内容：

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

    <Table class="rounded-xl border border-border bg-card shadow-sm">
      <TableHeader>
        <TableRow class="bg-card text-muted-foreground text-xs border-border">
          <TableHead class="h-10 px-3 text-center w-10">选择</TableHead>
          <TableHead v-for="col in columns" :key="col.key" class="h-10 px-3" :class="col.class || ''" :style="col.width ? { width: col.width } : {}">
            {{ col.label }}
          </TableHead>
          <TableHead class="h-10 px-3 text-center w-[100px]">操作</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody v-auto-animate>
        <TableRow v-for="(row, idx) in paginatedRows" :key="row.id"
          :data-row-id="row.id"
          class="text-sm animate-fade-in"
          :class="[
            highlightId != null && highlightId == row.id ? 'highlight-row' : '',
            isSelected(row.id) ? 'bg-muted/80 dark:bg-card/70' : 'bg-background'
          ]"
          :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
        >
          <TableCell class="px-3 py-2.5 text-center">
            <input type="checkbox" :checked="isSelected(row.id)" @change="$emit('toggle-item', row.id)"
              class="size-4 text-primary-600 rounded-md border-border focus:ring-primary-500 cursor-pointer transition">
          </TableCell>
          <TableCell v-for="col in columns" :key="col.key" class="px-3 py-2.5 break-words text-foreground" :class="col.cellClass || ''" :style="col.width ? { width: col.width } : {}">
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
              {{ row[col.frontendKey || col.key] }}
            </slot>
          </TableCell>
          <TableCell class="px-3 py-2.5 text-center">
            <slot name="actions" :row="row" />
          </TableCell>
        </TableRow>
        <TableRow v-if="rows.length === 0">
          <TableCell :colspan="columns.length + 2" class="p-16 text-center">
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Inbox />
                </EmptyMedia>
                <EmptyTitle>暂无数据</EmptyTitle>
                <EmptyDescription>试试切换筛选条件或录入更多内容</EmptyDescription>
              </EmptyHeader>
            </Empty>
          </TableCell>
        </TableRow>
      </TableBody>
    </Table>

    <div v-if="totalPages > 1" class="flex items-center justify-between gap-3 mt-4 px-1">
      <div class="text-xs text-muted-foreground tabular-nums">
        共 {{ rows.length }} 条，第 {{ currentPage }}/{{ totalPages }} 页
      </div>
      <Pagination v-slot="{ page }" :items-per-page="pageSize" :total="rows.length" :default-page="currentPage" @update:page="$emit('update:currentPage', $event)">
        <PaginationContent v-slot="{ items }">
          <PaginationPrevious />
          <template v-for="(item, index) in items" :key="index">
            <PaginationItem v-if="item.type === 'page'" :value="item.value" :is-active="item.value === page">
              {{ item.value }}
            </PaginationItem>
            <PaginationEllipsis v-else :index="item.value" />
          </template>
          <PaginationNext />
        </PaginationContent>
      </Pagination>
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <span>每页</span>
        <Select :model-value="String(pageSize)" @update:model-value="$emit('update:pageSize', Number($event)); $emit('update:currentPage', 1)">
          <SelectTrigger class="h-8 text-xs min-w-[60px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="s in [10, 20, 50, 100]" :key="s" :value="String(s)">{{ s }}</SelectItem>
          </SelectContent>
        </Select>
        <span>条</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Inbox } from '@lucide/vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Pagination, PaginationContent, PaginationEllipsis, PaginationItem, PaginationNext, PaginationPrevious } from '@/components/ui/pagination'
import BatchActionPanel from '@/components/common/BatchActionPanel.vue'

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

const totalPages = computed(() => Math.max(1, Math.ceil(props.rows.length / props.pageSize)))
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

- [ ] **Step 2: 验证构建**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build 2>&1 | tail -5
```

Expected: 构建成功（PaginationBar 不再被引用可安全删除）

- [ ] **Step 3: 删除 PaginationBar.vue**

```bash
rm /home/ubuntu/sj/interview-boss/frontend/src/components/common/PaginationBar.vue
```

- [ ] **Step 4: 再次验证构建**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build 2>&1 | tail -5
```

Expected: 构建成功

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/sj/interview-boss && git add -A && git commit -m "refactor(frontend): replace PaginationBar with shadcn Pagination in DataTable"
```

---

### Task 3: 统一 JD 库和面经库页头

**Files:**
- Modify: `views/JdView.vue` — 添加 Card 页头
- Modify: `views/InterviewView.vue` — 添加 Card 页头

两页使用相同的页头模式：图标 + 标题 + 副标题的 Card 容器。

- [ ] **Step 1: 更新 JdView.vue 页头**

在 `JdView.vue` 的 `<template>` 根 div 内、DataTable 之前添加页头 Card：

```vue
<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <!-- 页头 -->
    <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
      <div class="border-b border-border px-5 py-4">
        <div class="flex items-center gap-3">
          <div class="size-9 rounded-xl bg-gradient-brand flex items-center justify-center shadow-sm">
            <Briefcase class="size-5 text-white" />
          </div>
          <div>
            <h3 class="text-sm font-bold text-foreground">JD 库</h3>
            <p class="text-caption text-muted-foreground">管理岗位描述和招聘信息</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据表格 -->
    <JdDataTable ... />  <!-- 保持原有 props 不变 -->
  </div>
</template>
```

在 script 中添加 import: `import { Briefcase } from '@lucide/vue'`

- [ ] **Step 2: 更新 InterviewView.vue 页头**

在 InterviewView.vue 的 template 根 div 内、筛选栏之前添加同样的页头 Card（图标用 `FileText`，标题"面经库"，副标题"浏览和管理面试经验数据"）。筛选栏保持在页头下方。

- [ ] **Step 3: 验证构建**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
cd /home/ubuntu/sj/interview-boss && git add frontend/src/views/JdView.vue frontend/src/views/InterviewView.vue && git commit -m "refactor(frontend): add unified page headers to JD and Interview views"
```

---

### Task 4: 重构 MasterBankList 使用 Accordion

**Files:**
- Modify: `components/business/MasterBankList.vue` — 替换 DynamicScroller 为 Accordion
- Modify: `components/business/QuestionCard.vue` — 拆分为 AccordionTrigger + AccordionContent 结构

这是最大的改动。核心思路：
- AccordionTrigger = 当前 QuestionCard 的头部（题目标题 + badges + 星标 + checkbox）
- AccordionContent = 当前 QuestionCard 的答案区域（编辑/查看/来源）
- QuestionCard 保留为内部组件，但改为接收 `expanded` prop 控制展开状态

- [ ] **Step 1: 修改 QuestionCard.vue 支持 Accordion 模式**

在 QuestionCard.vue 的 props 中添加：
```js
accordionMode: { type: Boolean, default: false }
```

当 `accordionMode` 为 true 时：
- 根容器去掉 `cursor-pointer @click` 和展开 chevron
- 头部通过 `#trigger` slot 输出（供 AccordionTrigger 使用）
- 答案区域通过 `#content` slot 输出（供 AccordionContent 使用）
- `_showAnswer` 由外部 Accordion 控制，不再由内部 toggle

具体做法：将 QuestionCard 的 template 拆为三个 slot 区域：
1. `#trigger` — 题目标题 + badges + 操作按钮（checkbox, star, practice, chevron 除外）
2. `#content` — 答案/来源区域（当前 `v-if="question._showAnswer"` 的内容）
3. 默认 slot — 完整渲染（非 Accordion 模式时的 fallback）

实际实现：不改 QuestionCard 的内部逻辑，而是在 MasterBankList 中用 Accordion 包裹 QuestionCard 的内容。QuestionCard 的 `_showAnswer` 由 Accordion 的 open 状态同步。

- [ ] **Step 2: 重写 MasterBankList.vue 使用 Accordion**

替换 DynamicScroller 为 Accordion：

```vue
<template>
  <div v-if="items.length === 0">
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Inbox />
        </EmptyMedia>
        <EmptyTitle>题库空空如也</EmptyTitle>
        <EmptyDescription>导入面经或 JD 来生成面试题</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button @click="$emit('navigate-to-import')">开始导入</Button>
      </EmptyContent>
    </Empty>
  </div>

  <div v-else class="flex flex-col gap-3">
    <!-- 操作栏 -->
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="items.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    >
      <Button variant="outline" size="sm" @click="$emit('expand-all')">全部展开</Button>
      <Button variant="outline" size="sm" @click="$emit('collapse-all')">全部收起</Button>
      <template #right>
        <slot name="actions" />
      </template>
    </BatchActionPanel>

    <!-- scroll-header slot -->
    <slot name="scroll-header" />

    <!-- Accordion 题目列表 -->
    <Accordion type="multiple" v-model="openItems" class="flex flex-col gap-2">
      <AccordionItem
        v-for="q in items"
        :key="q.id"
        :value="String(q.id)"
        class="border border-border rounded-xl overflow-hidden bg-card shadow-sm data-[state=open]:border-primary/30"
      >
        <AccordionTrigger class="px-4 py-3 hover:no-underline [&[data-state=open]>svg]:hidden">
          <div class="flex items-center gap-3 flex-1 min-w-0 text-left">
            <input type="checkbox" :checked="isSelected(q.id)" @click.stop="$emit('toggle-item', q.id)"
              class="size-4 text-primary-600 rounded-md border-border cursor-pointer shrink-0">
            <div class="flex-1 min-w-0">
              <span class="text-sm font-medium text-foreground truncate block">{{ q.question }}</span>
              <div class="flex gap-1.5 mt-1 flex-wrap items-center">
                <span v-if="q.frequency > 1" class="text-xs px-1.5 py-0.5 rounded bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 font-bold">{{ q.frequency }}x</span>
                <span class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
                <span v-for="tag in (q.tags || '').split(',').filter(Boolean).slice(0, 3)" :key="tag"
                  class="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{{ tag.trim() }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded ml-auto" :class="difficultyClass(q.difficulty)">
                  {{ q.difficulty || '-' }}
                </span>
              </div>
            </div>
          </div>
        </AccordionTrigger>
        <AccordionContent class="px-4 pb-4">
          <QuestionCard
            :question="q"
            :is-selected="isSelected"
            :practice-info="practicedQuestions?.[q.id]"
            :bank-mode="bankMode"
            :is-admin="isAdmin"
            :current-user-id="currentUserId"
            :accordion-mode="true"
            @toggle-star="$emit('toggle-star', $event)"
            @retag="$emit('retag', $event)"
            @generate-answer="$emit('generate-answer', $event)"
            @use-reference-answer="$emit('use-reference-answer', $event)"
            @save-user-answer="$emit('save-user-answer', $event)"
            @save-field="$emit('save-field', $event)"
            @practice="$emit('practice', $event)"
            @split-question="$emit('split-question', $event)"
            @start-merge="$emit('start-merge', $event)"
            @navigate-to-interview="$emit('navigate-to-interview', $event)"
            @delete="$emit('delete', $event)"
            @edit-question="$emit('edit-question', $event)"
            @delete-original-question="$emit('delete-original-question', $event)"
            @update-answer="$emit('update-answer', $event)"
          />
        </AccordionContent>
      </AccordionItem>
    </Accordion>

    <!-- 加载更多 -->
    <div v-if="isLoadingMore" class="text-center py-4 text-sm text-muted-foreground">
      <Loader2 class="size-5 animate-spin mx-auto mb-1" />
      加载更多题目...
    </div>
    <div v-else-if="!hasMore && items.length > 0" class="text-center py-4 text-xs text-muted-foreground">
      已加载全部 {{ items.length }} 道题目
    </div>
  </div>
</template>
```

script 部分添加：
```js
import { ref, watch } from 'vue'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Loader2, Inbox } from '@lucide/vue'

const openItems = ref([])

// 同步 _showAnswer 状态
watch(openItems, (newVal) => {
  items.value.forEach(q => {
    q._showAnswer = newVal.includes(String(q.id))
  })
})

// 全部展开/收起
function expandAll() { openItems.value = items.value.map(q => String(q.id)) }
function collapseAll() { openItems.value = [] }
```

- [ ] **Step 3: 在 QuestionCard.vue 添加 accordionMode 支持**

在 QuestionCard 的 template 中，当 `accordionMode` 为 true 时：
- 隐藏头部区域（因为 AccordionTrigger 已经渲染了标题和 badges）
- 只显示答案区域 + 操作按钮
- 隐藏展开 chevron 和 checkbox（已在 AccordionTrigger 中）

在 QuestionCard 的 root div 添加条件 class：
```vue
<div v-if="!accordionMode" ... > <!-- 原有完整渲染 -->
</div>
<div v-else> <!-- Accordion 模式：只渲染内容区 -->
  <!-- 答案区域 -->
  <!-- 来源区域 -->
  <!-- 操作按钮 -->
</div>
```

- [ ] **Step 4: 验证构建**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
cd /home/ubuntu/sj/interview-boss && git add frontend/src/components/business/MasterBankList.vue frontend/src/components/business/QuestionCard.vue && git commit -m "refactor(frontend): replace card list with shadcn Accordion in MasterBank"
```

---

### Task 5: 删除 AppEmpty 并部署验证

**Files:**
- Delete: `components/common/AppEmpty.vue`
- Verify: 所有三个页面功能正常

- [ ] **Step 1: 确认 AppEmpty 无其他引用**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && grep -r "AppEmpty" src/ --include="*.vue" --include="*.js"
```

Expected: 只在 MasterBankList.vue 中有引用（已在 Task 4 中替换为 shadcn Empty）

- [ ] **Step 2: 删除 AppEmpty.vue**

```bash
rm /home/ubuntu/sj/interview-boss/frontend/src/components/common/AppEmpty.vue
```

- [ ] **Step 3: 最终构建验证**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
cd /home/ubuntu/sj/interview-boss && git add -A && git commit -m "chore(frontend): remove unused AppEmpty and PaginationBar components"
```

- [ ] **Step 5: 部署前端**

```bash
./deploy/docker-deploy.sh frontend
```

- [ ] **Step 6: 生产验证**

在浏览器中验证三个页面：
- 高频题库：Accordion 折叠/展开正常，批量操作正常，分页正常
- JD 库：页头显示，表格分页正常，空状态显示
- 面经库：页头显示，筛选+排序正常，分页正常

---

## 实施顺序总结

```
Task 1: 安装 shadcn 组件 (accordion, pagination, empty)
  ↓
Task 2: DataTable 分页升级 (PaginationBar → shadcn Pagination)
  ↓
Task 3: JD/Interview 统一页头
  ↓
Task 4: MasterBank Accordion 重构 (最大改动)
  ↓
Task 5: 清理废弃组件 + 部署验证
```

每个 Task 独立可 commit，可回滚。

# InterviewBoss UI/UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish InterviewBoss navigation, mobile usability, icons, and hierarchy while preserving the existing color palette and workflows.

**Architecture:** Keep the current Vue Router and layout structure. Add a grouped navigation data model in `AuthenticatedLayout.vue`, render it through `AppSidebar.vue` on desktop and a Sheet-backed mobile nav in the shell, then make data-heavy and split-pane pages responsive without changing their business flows.

**Tech Stack:** Vue 3 Composition API, Vue Router 4, Tailwind CSS, shadcn-vue/reka-ui primitives, `@lucide/vue`, Playwright.

## Global Constraints

- Keep the existing color palette and brand direction.
- Do not redesign the core product narrative into a new dashboard.
- Preserve current routes, data flow, API contracts, and page-level behavior.
- Use `@lucide/vue` for new or replaced icons.
- Mobile users must be able to switch routes and use Chat, Coding, JD, Interview, and MasterBank at 390px width.
- Existing import submission contract must remain unchanged.
- Frontend UI copy remains Simplified Chinese.
- Do not create a new branch or worktree unless the user asks; this repo normally works directly on `master`.

---

## File Structure

- `frontend/tests/e2e/ui-responsive-polish.spec.js`: New Playwright regression tests for grouped nav, mobile route switching, mobile data cards, and mobile split-pane usability.
- `frontend/src/layouts/AuthenticatedLayout.vue`: Owns grouped sidebar data, mobile nav open state, and Sheet-backed mobile route menu.
- `frontend/src/components/AppSidebar.vue`: Renders grouped desktop sidebar and uses lucide icons.
- `frontend/src/components/SiteHeader.vue`: Adds mobile menu trigger and replaces inline status SVGs with lucide icons.
- `frontend/src/components/common/DataTable.vue`: Keeps desktop table, adds mobile card rendering for textual data.
- `frontend/src/views/JdView.vue`: Supplies mobile-friendly labels/fields through existing slots and lucide action icons.
- `frontend/src/views/InterviewView.vue`: Supplies mobile-friendly labels/fields through existing slots and lucide action icons.
- `frontend/src/components/business/ChatView.vue`: Converts internal conversation sidebar to a mobile overlay/toggle while preserving desktop layout.
- `frontend/src/components/business/CodingPractice.vue`: Converts internal problem sidebar to a mobile overlay/toggle while preserving desktop layout.
- `frontend/src/components/business/MasterBankList.vue`: Fixes mobile accordion control spacing and chevron clipping.
- `frontend/src/components/business/StagingPanel.vue`: Light polish only; preserve combined text + image upload.
- `frontend/CLAUDE.md`: Add a durable frontend convention if the implementation establishes mobile card rows or grouped navigation as a standard.

---

### Task 1: Responsive UI Regression Tests

**Files:**
- Create: `frontend/tests/e2e/ui-responsive-polish.spec.js`

**Interfaces:**
- Consumes: Existing preview routes with `?preview=1`.
- Produces: Failing tests that define the UI/UX polish contract for later tasks.

- [ ] **Step 1: Write failing Playwright tests**

Create `frontend/tests/e2e/ui-responsive-polish.spec.js` with:

```js
import { test, expect } from '@playwright/test'

const preview = (path) => `${path}?preview=1`

async function gotoPreview(page, path, viewport = { width: 390, height: 844 }) {
  await page.setViewportSize(viewport)
  await page.goto(preview(path), { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('main', { timeout: 15000 })
  await page.waitForTimeout(700)
}

async function expectNoHorizontalOverflow(page) {
  const metrics = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.width + 1)
}

test.describe('UI responsive polish', () => {
  test('desktop sidebar uses grouped workflow order', async ({ page }) => {
    await gotoPreview(page, '/master-bank', { width: 1440, height: 900 })
    const sidebar = page.locator('aside')
    await expect(sidebar.getByText('高频题库')).toBeVisible()
    await expect(sidebar.getByText('训练')).toBeVisible()
    await expect(sidebar.getByText('素材')).toBeVisible()
    await expect(sidebar.getByText('洞察')).toBeVisible()

    const labels = await sidebar.locator('[data-sidebar-route], [data-sidebar-section]').evaluateAll((nodes) =>
      nodes.map((node) => node.textContent.trim().replace(/\s+/g, ' '))
    )
    expect(labels).toEqual([
      '高频题库 3',
      '训练',
      '模拟面试',
      '题目抽测',
      '手撕代码',
      '素材',
      '导入',
      'JD 筛选 2',
      '面经库 2',
      '洞察',
      '知识图谱',
    ])
  })

  test('mobile shell navigation opens and switches routes', async ({ page }) => {
    await gotoPreview(page, '/master-bank')
    await page.getByRole('button', { name: '打开导航' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: /导入/ }).click()
    await expect(page).toHaveURL(/\/import\?preview=1/)
    await expect(page.getByRole('heading', { name: '导入' })).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test('mobile JD and interview data render as cards, not compressed tables', async ({ page }) => {
    await gotoPreview(page, '/jd')
    await expect(page.locator('[data-mobile-row-card]').first()).toBeVisible()
    await expect(page.locator('table')).toBeHidden()
    await expect(page.getByText('Moonshot AI')).toBeVisible()
    await expectNoHorizontalOverflow(page)

    await gotoPreview(page, '/interview')
    await expect(page.locator('[data-mobile-row-card]').first()).toBeVisible()
    await expect(page.locator('table')).toBeHidden()
    await expect(page.getByText('腾讯')).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test('mobile chat keeps active conversation readable and switchable', async ({ page }) => {
    await gotoPreview(page, '/chat')
    await expect(page.getByRole('button', { name: '切换面试会话' })).toBeVisible()
    const main = page.locator('main')
    const box = await main.boundingBox()
    expect(box.width).toBeGreaterThanOrEqual(360)
    await expect(page.getByText('如果遇到一份格式很乱的面经')).toBeVisible()
    await expectNoHorizontalOverflow(page)
  })

  test('mobile coding keeps main content readable and problem list switchable', async ({ page }) => {
    await gotoPreview(page, '/coding')
    await expect(page.getByRole('button', { name: '选择题目' })).toBeVisible()
    await expect(page.getByText('开始编码练习')).toBeVisible()
    const main = page.locator('main')
    const box = await main.boundingBox()
    expect(box.width).toBeGreaterThanOrEqual(360)
    await expectNoHorizontalOverflow(page)
  })

  test('mobile master bank cards keep controls inside viewport', async ({ page }) => {
    await gotoPreview(page, '/master-bank')
    const viewportWidth = await page.evaluate(() => document.documentElement.clientWidth)
    const overflowingButtons = await page.locator('button').evaluateAll((buttons, width) =>
      buttons
        .map((button) => button.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && (rect.left < -1 || rect.right > width + 1))
        .length,
      viewportWidth
    )
    expect(overflowingButtons).toBe(0)
    await expectNoHorizontalOverflow(page)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend && npx playwright test tests/e2e/ui-responsive-polish.spec.js
```

Expected: FAIL. At minimum, the mobile nav trigger, sidebar section labels, and `data-mobile-row-card` elements do not exist yet.

- [ ] **Step 3: Commit failing tests**

```bash
git add frontend/tests/e2e/ui-responsive-polish.spec.js
git commit -m "test(frontend): add responsive ui polish coverage"
```

---

### Task 2: Grouped Sidebar, Mobile Shell Navigation, And Lucide Chrome Icons

**Files:**
- Modify: `frontend/src/layouts/AuthenticatedLayout.vue`
- Modify: `frontend/src/components/AppSidebar.vue`
- Modify: `frontend/src/components/SiteHeader.vue`

**Interfaces:**
- Consumes: `sidebarTabs` route metadata currently built in `AuthenticatedLayout.vue`.
- Produces: `sidebarGroups` with `{ label: string | null, tabs: Array<Tab> }`; mobile nav trigger named `打开导航`; desktop elements tagged with `data-sidebar-section` and `data-sidebar-route`.

- [ ] **Step 1: Implement grouped navigation data in `AuthenticatedLayout.vue`**

Replace the existing flat `sidebarTabs` computed with grouped route data and a flat compatibility computed:

```js
const sidebarGroups = computed(() => [
  {
    label: null,
    tabs: [
      { key: 'MasterBank', label: '高频题库', route: '/master-bank', count: masterBankTotal.value || filteredMasterBank.value.length },
    ],
  },
  {
    label: '训练',
    tabs: [
      { key: 'Chat', label: '模拟面试', route: '/chat' },
      { key: 'MockInterview', label: '题目抽测', route: '/mock-interview' },
      { key: 'Coding', label: '手撕代码', route: '/coding' },
    ],
  },
  {
    label: '素材',
    tabs: [
      { key: 'Import', label: '导入', route: '/import' },
      { key: 'JD', label: 'JD 筛选', route: '/jd', count: jdData.value.length },
      { key: 'Interview', label: '面经库', route: '/interview', count: interviewData.value.length },
    ],
  },
  {
    label: '洞察',
    tabs: [
      { key: 'KnowledgeGraph', label: '知识图谱', route: '/knowledge-graph' },
    ],
  },
])

const sidebarTabs = computed(() => sidebarGroups.value.flatMap(group => group.tabs))
const mobileNavOpen = ref(false)
const closeMobileNav = () => { mobileNavOpen.value = false }
```

Pass both groups and flat tabs:

```vue
<AppSidebar
  :collapsed="sidebarCollapsed"
  :active-tab="activeTab"
  :sidebar-tabs="sidebarTabs"
  :sidebar-groups="sidebarGroups"
  :display-user="displayUser"
  :pending-review-count="pendingReviewCount"
  @update:active-tab="activeTab = $event"
  @update:collapsed="sidebarCollapsed = $event"
  @go-to-question="onGoToQuestion"
  @logout="handleLogout"
  @bank-mode-changed="handleBankModeChanged"
  @show-review="showReviewPanel = true"
  @show-settings="openSettings"
/>
<SiteHeader
  :active-tab-label="activeTabLabel"
  :active-season="activeSeason"
  :no-border="route.path.startsWith('/chat')"
  @show-settings="openSettings"
  @toggle-mobile-nav="mobileNavOpen = true"
/>
```

Render mobile `Sheet` after `SiteHeader` in the main shell:

```vue
<Sheet v-model:open="mobileNavOpen">
  <SheetContent side="left" class="w-[320px] max-w-[calc(100vw-2rem)] gap-0 p-0">
    <SheetHeader class="sr-only">
      <SheetTitle>导航</SheetTitle>
      <SheetDescription>切换 InterviewBoss 工作区</SheetDescription>
    </SheetHeader>
    <div class="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div class="flex items-center gap-3 border-b border-sidebar-border/60 px-4 py-4">
        <img src="/favicon-b.png" alt="InterviewBoss" class="h-8 w-8 object-contain" />
        <div class="min-w-0">
          <div class="truncate text-base font-semibold">InterviewBoss</div>
          <div class="truncate text-caption text-sidebar-foreground/50">AI 面试准备工作台</div>
        </div>
      </div>
      <nav class="flex-1 overflow-y-auto p-3">
        <template v-for="group in sidebarGroups" :key="group.label || 'primary'">
          <div v-if="group.label" class="px-2 pb-1 pt-3 text-label text-sidebar-foreground/45">{{ group.label }}</div>
          <button
            v-for="tab in group.tabs"
            :key="tab.key"
            type="button"
            class="flex h-10 w-full items-center gap-3 rounded-lg px-3 text-sm transition-colors"
            :class="isActiveRoute(tab.route) ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium' : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'"
            @click="navigateMobile(tab.route)"
          >
            <component :is="navIconMap[tab.key]" class="size-4 shrink-0" />
            <span class="min-w-0 flex-1 truncate text-left">{{ tab.label }}</span>
            <span v-if="tab.count != null && tab.count !== 0" class="text-caption text-sidebar-foreground/50">{{ tab.count }}</span>
          </button>
        </template>
      </nav>
    </div>
  </SheetContent>
</Sheet>
```

Add helpers in script:

```js
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { BookOpen, BotMessageSquare, ClipboardList, Code2, FileUp, Filter, Library, Network } from '@lucide/vue'

const navIconMap = {
  MasterBank: BookOpen,
  Chat: BotMessageSquare,
  MockInterview: ClipboardList,
  Coding: Code2,
  Import: FileUp,
  JD: Filter,
  Interview: Library,
  KnowledgeGraph: Network,
}

const isActiveRoute = (tabRoute) => route.path === tabRoute || route.path.startsWith(tabRoute + '/')
const navigateMobile = async (path) => {
  await router.push({ path, query: isPreviewMode ? { preview: '1' } : undefined })
  closeMobileNav()
}
```

- [ ] **Step 2: Update `AppSidebar.vue` to render groups and lucide icons**

Use `sidebarGroups` with a fallback derived from `sidebarTabs`:

```js
import {
  BookOpen,
  BotMessageSquare,
  ClipboardList,
  Code2,
  FileUp,
  Filter,
  Library,
  Network,
  PanelLeft,
} from '@lucide/vue'

const groupedTabs = computed(() => props.sidebarGroups?.length
  ? props.sidebarGroups
  : [{ label: null, tabs: props.sidebarTabs }]
)

const iconMap = {
  MasterBank: BookOpen,
  Chat: BotMessageSquare,
  MockInterview: ClipboardList,
  Coding: Code2,
  Import: FileUp,
  JD: Filter,
  Interview: Library,
  KnowledgeGraph: Network,
}
```

In expanded mode, render:

```vue
<template v-for="group in groupedTabs" :key="group.label || 'primary'">
  <div
    v-if="group.label"
    data-sidebar-section
    class="px-3 pb-1 pt-3 text-label text-sidebar-foreground/40"
  >
    {{ group.label }}
  </div>
  <button
    v-for="tab in group.tabs"
    :key="tab.key"
    data-sidebar-route
    @click="onTabChange(tab)"
    class="group relative flex h-9 w-full items-center gap-3 rounded-lg px-3 text-sm transition-colors"
    :class="isActive(tab.route)
      ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
      : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
  >
    <component
      :is="iconMap[tab.key]"
      v-if="iconMap[tab.key]"
      class="size-4 shrink-0 transition-colors"
      :class="isActive(tab.route) ? 'text-primary' : 'text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70'"
    />
    <span class="min-w-0 flex-1 truncate text-left">{{ tab.label }}</span>
    <span v-if="tab.count != null && tab.count !== 0" class="text-caption font-medium text-sidebar-foreground/50">{{ tab.count }}</span>
  </button>
</template>
```

In collapsed mode, flatten groups and keep tooltips:

```vue
<AppTooltip
  v-for="tab in groupedTabs.flatMap(group => group.tabs)"
  :key="tab.key"
  :text="tab.label"
  side="right"
>
  <button
    type="button"
    data-sidebar-route
    class="flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-300"
    :class="isActive(tab.route)
      ? 'bg-sidebar-accent text-sidebar-accent-foreground'
      : 'text-sidebar-foreground/50 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
    @click="onTabChange(tab)"
  >
    <component :is="iconMap[tab.key]" v-if="iconMap[tab.key]" class="size-4" />
  </button>
</AppTooltip>
```

- [ ] **Step 3: Add mobile nav trigger and lucide status icons in `SiteHeader.vue`**

Add emit and imports:

```js
import { AlertCircle, CheckCircle2, Clock3, Loader2, Menu, Settings, X } from '@lucide/vue'
const emit = defineEmits(['show-settings', 'toggle-mobile-nav'])
```

Place a mobile trigger before the title:

```vue
<AppTooltip text="打开导航">
  <Button
    variant="ghost"
    size="icon"
    class="inline-flex h-8 w-8 items-center justify-center text-muted-foreground md:hidden"
    aria-label="打开导航"
    @click="emit('toggle-mobile-nav')"
  >
    <Menu class="h-4 w-4" />
  </Button>
</AppTooltip>
```

Replace task status inline SVGs:

```vue
<Loader2 v-if="primaryJob?.status === 'running'" class="size-3.5 animate-spin text-blue-500" />
<AlertCircle v-else-if="primaryJob?.status === 'failed'" class="size-3.5 text-red-500" />
<Clock3 v-else class="size-3.5 text-amber-500" />
<CheckCircle2 v-if="job.status === 'completed'" class="size-3.5 text-green-500" />
<AlertCircle v-else-if="job.status === 'failed'" class="size-3.5 text-red-500" />
<Clock3 v-else-if="job.status === 'pending'" class="size-3.5 text-amber-500" />
<Loader2 v-else class="size-3.5 animate-spin text-blue-500" />
<X class="size-3.5" />
```

- [ ] **Step 4: Run tests for Task 2**

Run:

```bash
cd frontend && npx playwright test tests/e2e/ui-responsive-polish.spec.js --grep "sidebar|mobile shell"
```

Expected: sidebar and mobile shell tests pass. Data cards and split-pane tests may still fail until later tasks.

- [ ] **Step 5: Commit Task 2**

```bash
git add frontend/src/layouts/AuthenticatedLayout.vue frontend/src/components/AppSidebar.vue frontend/src/components/SiteHeader.vue
git commit -m "feat(frontend): group navigation and add mobile shell menu"
```

---

### Task 3: Mobile Data Cards For Shared Tables

**Files:**
- Modify: `frontend/src/components/common/DataTable.vue`
- Modify: `frontend/src/views/JdView.vue`
- Modify: `frontend/src/views/InterviewView.vue`

**Interfaces:**
- Consumes: `columns`, `paginatedRows`, existing `cell-*` and `actions` slots.
- Produces: Mobile-only cards tagged with `data-mobile-row-card`; desktop table hidden below `md`.

- [ ] **Step 1: Add mobile cards to `DataTable.vue`**

Wrap the current table container in `hidden md:block`:

```vue
<div class="hidden w-full min-w-0 overflow-hidden rounded-xl border border-border bg-card shadow-sm md:block">
  <!-- Move the existing Table/Header/Body markup here unchanged. -->
</div>
```

Add this mobile block immediately after the desktop table:

```vue
<div class="flex flex-col gap-3 md:hidden">
  <article
    v-for="row in paginatedRows"
    :key="row.id"
    data-mobile-row-card
    :data-row-id="row.id"
    class="rounded-xl border border-border bg-card p-3 shadow-sm"
    :class="[
      highlightId != null && highlightId == row.id ? 'highlight-row' : '',
      isSelected(row.id) ? 'bg-muted/70' : ''
    ]"
  >
    <div class="mb-3 flex items-start gap-3">
      <input
        type="checkbox"
        :checked="isSelected(row.id)"
        class="mt-1 size-4 shrink-0 rounded-md border-border text-primary-600 focus:ring-primary-500"
        @change="$emit('toggle-item', row.id)"
      >
      <div class="min-w-0 flex-1">
        <div class="text-caption font-medium text-muted-foreground">#{{ row.id }}</div>
        <div class="mt-1 grid gap-2">
          <div
            v-for="col in columns"
            :key="col.key"
            class="grid gap-1"
          >
            <div class="text-caption font-medium text-muted-foreground">{{ col.label }}</div>
            <div class="min-w-0 break-words text-sm leading-relaxed text-foreground">
              <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
                {{ row[col.frontendKey || col.key] }}
              </slot>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="flex items-center justify-end gap-2 border-t border-border/70 pt-2">
      <slot name="actions" :row="row" />
    </div>
  </article>
  <Empty v-if="rows.length === 0">
    <EmptyHeader>
      <EmptyMedia variant="icon"><Inbox /></EmptyMedia>
      <EmptyTitle>暂无数据</EmptyTitle>
      <EmptyDescription>试试切换筛选条件或录入更多内容</EmptyDescription>
    </EmptyHeader>
  </Empty>
</div>
```

- [ ] **Step 2: Replace JD inline SVG action icons with lucide icons**

In `JdView.vue`, import:

```js
import { Briefcase, ExternalLink, Trash2 } from '@lucide/vue'
```

Replace the action SVGs:

```vue
<ExternalLink class="size-4" />
<Trash2 class="size-4" />
```

- [ ] **Step 3: Replace Interview inline SVG action icons with lucide icons**

In `InterviewView.vue`, import:

```js
import { ArrowLeft, ExternalLink, FileText, Loader2, RefreshCw, SortAsc, SortDesc, Trash2 } from '@lucide/vue'
```

Replace the sort, refresh, loading, external link, delete, and return SVGs:

```vue
<SortDesc v-if="interviewSortOrder === 'desc'" class="size-3.5" />
<SortAsc v-else class="size-3.5" />
<Loader2 v-if="reprocessingIds[row.id]" class="size-4 animate-spin" />
<RefreshCw v-else class="size-4" />
<ExternalLink class="size-4" />
<Trash2 class="size-4" />
<ArrowLeft class="size-3" />
```

- [ ] **Step 4: Run tests for Task 3**

Run:

```bash
cd frontend && npx playwright test tests/e2e/ui-responsive-polish.spec.js --grep "JD and interview"
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add frontend/src/components/common/DataTable.vue frontend/src/views/JdView.vue frontend/src/views/InterviewView.vue
git commit -m "feat(frontend): add mobile cards for data tables"
```

---

### Task 4: Mobile Split-Pane Fixes For Chat And Coding

**Files:**
- Modify: `frontend/src/components/business/ChatView.vue`
- Modify: `frontend/src/components/business/CodingPractice.vue`

**Interfaces:**
- Consumes: Existing `sidebarCollapsed` state in each component.
- Produces: Mobile sidebars that overlay instead of consuming layout width; buttons named `切换面试会话` and `选择题目`.

- [ ] **Step 1: Initialize internal sidebars collapsed on mobile**

In both components, initialize:

```js
const sidebarCollapsed = ref(window.matchMedia?.('(max-width: 767px)').matches ?? false)
```

If `sidebarCollapsed` already exists, replace only its initializer.

- [ ] **Step 2: Add accessible mobile toggle labels**

In `ChatView.vue`, change the collapsed expand button:

```vue
<Button
  variant="ghost"
  size="icon"
  aria-label="切换面试会话"
  @click="sidebarCollapsed = false"
  class="shrink-0"
>
  <PanelLeft :size="16" />
</Button>
```

In `CodingPractice.vue`, change the collapsed expand button:

```vue
<Button
  variant="ghost"
  size="icon"
  aria-label="选择题目"
  @click="sidebarCollapsed = false"
  class="shrink-0"
>
  <PanelLeft :size="16" />
</Button>
```

- [ ] **Step 3: Make internal sidebars overlay on mobile**

Add this scoped CSS to both components:

```css
@media (max-width: 767px) {
  .sidebar-container {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: 30;
    width: min(320px, calc(100vw - 48px)) !important;
    background: var(--background);
    box-shadow: 0 16px 40px rgb(0 0 0 / 0.14);
  }

  .sidebar-container.sidebar-collapsed {
    width: 0 !important;
    border-right-width: 0;
    box-shadow: none;
  }

  .sidebar-expand-buttons {
    position: absolute;
    left: 0;
    bottom: 0.5rem;
    z-index: 20;
    border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
    background: var(--background);
  }
}
```

Ensure the root wrapper has `relative overflow-hidden`:

```vue
<div class="relative flex h-full overflow-hidden bg-background">
```

- [ ] **Step 4: Run tests for Task 4**

Run:

```bash
cd frontend && npx playwright test tests/e2e/ui-responsive-polish.spec.js --grep "chat|coding"
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add frontend/src/components/business/ChatView.vue frontend/src/components/business/CodingPractice.vue
git commit -m "fix(frontend): make split panes usable on mobile"
```

---

### Task 5: MasterBank, Import Polish, Docs, And Final Verification

**Files:**
- Modify: `frontend/src/components/business/MasterBankList.vue`
- Modify: `frontend/src/views/MasterBankView.vue`
- Modify: `frontend/src/components/business/StagingPanel.vue`
- Modify: `frontend/CLAUDE.md`

**Interfaces:**
- Consumes: Existing MasterBank accordion and Import form.
- Produces: Mobile-safe accordion controls, clearer action wrapping, preserved import contract, and durable frontend guidance.

- [ ] **Step 1: Fix MasterBank mobile accordion spacing**

In `MasterBankList.vue`, update the trigger and inner structure:

```vue
<AccordionItem
  v-for="q in items"
  :key="q.id"
  :value="String(q.id)"
  class="min-w-0 border border-border rounded-xl overflow-hidden bg-card shadow-sm data-[state=open]:border-primary/30"
>
  <AccordionTrigger class="w-full px-3 py-3 hover:no-underline md:px-4 [&>svg]:ml-2 [&>svg]:shrink-0">
    <div class="flex min-w-0 flex-1 items-center gap-3 text-left">
      <input
        type="checkbox"
        :checked="isSelected(q.id)"
        class="size-4 shrink-0 text-primary-600 rounded-md border-border cursor-pointer"
        @click.stop="$emit('toggle-item', q.id)"
      />
      <div class="min-w-0 flex-1">
        <span class="block truncate text-sm font-medium text-foreground">{{ q.question }}</span>
        <div class="mt-1 flex min-w-0 flex-wrap items-center gap-1.5">
          <span v-if="q.frequency > 1" class="text-xs px-1.5 py-0.5 rounded-md bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 font-bold">{{ q.frequency }}x</span>
          <span class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded-md font-semibold">{{ q.cat1 || '未分类' }}</span>
          <span
            v-for="tag in (q.tags || '').split(',').filter(Boolean).slice(0, 3)"
            :key="tag"
            class="text-xs px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground"
          >{{ tag.trim() }}</span>
          <span class="text-xs font-medium px-2 py-0.5 rounded-md" :class="difficultyClass(q.difficulty)">
            {{ q.difficulty || '-' }}
          </span>
        </div>
      </div>
    </div>
  </AccordionTrigger>
</AccordionItem>
```

Remove `ml-auto` from the difficulty badge in the trigger so it wraps naturally on mobile.

- [ ] **Step 2: Make MasterBank toolbar action wrapping predictable**

In `MasterBankView.vue`, keep search first, then batch actions, then primary actions. The existing structure can remain, but update right action wrapper:

```vue
<template #right>
  <div class="flex w-full flex-wrap items-center justify-start gap-2 sm:w-auto sm:justify-end">
    <Button v-if="displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildMasterBank" :disabled="isBuilding">
      {{ isBuilding ? '重建中...' : '重建题库' }}
    </Button>
    <Button v-if="!displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildPersonalBank" :disabled="isBuilding">
      {{ isBuilding ? '重建中...' : '重建题库' }}
    </Button>
    <Button v-if="filteredMasterBank.length > 0" variant="outline" size="sm" @click="enterPracticeMode">
      刷题模式
    </Button>
    <Button v-if="!isDataLoading" variant="outline" size="sm" @click="fetchTableData" :disabled="isDataLoading">
      刷新
    </Button>
  </div>
</template>
```

Keep the toolbar container class:

```vue
<div class="rounded-xl border border-border bg-card p-3 shadow-sm flex flex-col gap-3 shrink-0">
```

Keep this container; do not split the page into a new dashboard.

- [ ] **Step 3: Light Import polish without changing the submission contract**

In `StagingPanel.vue`, only adjust spacing and grouping:

```vue
<div class="flex min-h-0 flex-1 flex-col gap-4">
  <div class="flex flex-wrap items-center gap-2 rounded-lg border border-border/70 bg-card px-3 py-2">
    <Badge v-if="activeJobCount > 0" variant="secondary" class="gap-1.5 text-xs">
      <span class="relative flex h-2 w-2">
        <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
        <span class="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
      {{ activeJobCount }} 个任务处理中
    </Badge>
    <p class="text-xs text-muted-foreground">
      粘贴文本、补充截图或填写来源链接，提交后由后台任务完成提取和归档。
    </p>
  </div>
  <div class="flex flex-col gap-3 rounded-lg border bg-card p-3 shadow-sm sm:flex-row sm:items-end sm:p-4">
```

Do not change `FormData` fields:

```js
formData.append('url', sourceUrl.value.trim())
formData.append('text', rawText.value.slice(0, TEXT_MAX_LENGTH))
formData.append('season', importConfig.season || props.activeSeason || '2027届暑期实习')
formData.append('target', props.isAdmin ? importConfig.target : 'personal')
if (importConfig.type !== 'auto') {
  formData.append('content_type', importConfig.type)
}
images.value.forEach(item => formData.append('files', item.file))
```

- [ ] **Step 4: Update `frontend/CLAUDE.md` with durable convention**

Add under UI consistency baseline:

```markdown
- 侧边栏导航按工作流分组：高频题库置顶，训练（模拟面试/题目抽测/手撕代码），素材（导入/JD 筛选/面经库），洞察（知识图谱）。移动端导航必须使用同一分组。
- 数据表在桌面保留表格；在 390px 级移动端必须使用可读卡片或显式横向滚动，禁止把文本列压成竖排字。
- Chat/Coding 这类内部左右分栏页面，在移动端必须把内部侧栏改为抽屉/覆盖面板，不能挤压主内容。
```

If the file already has equivalent guidance, merge wording instead of duplicating.

- [ ] **Step 5: Run full verification**

Run:

```bash
cd frontend && npm run build
cd frontend && npx playwright test tests/e2e/ui-responsive-polish.spec.js
```

Expected: both PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add frontend/src/components/business/MasterBankList.vue frontend/src/views/MasterBankView.vue frontend/src/components/business/StagingPanel.vue frontend/CLAUDE.md
git commit -m "fix(frontend): polish mobile hierarchy and docs"
```

---

## Plan Self-Review

Spec coverage:

- Icon unification: Task 2 and Task 3 cover shared chrome and touched high-traffic components.
- Sidebar order: Task 2 implements grouped workflow navigation.
- Mobile shell: Task 2 implements global mobile navigation; Task 4 fixes internal mobile sidebars.
- Mobile data presentation: Task 3 adds mobile cards for shared tables.
- MasterBank controls: Task 5 fixes accordion and toolbar spacing.
- Import contract: Task 5 explicitly preserves the FormData contract.
- Verification: Task 1 defines regression coverage; Task 5 runs build and focused Playwright tests.

Placeholder scan:

- No `TBD`, `TODO`, or unspecified implementation placeholders remain.

Type consistency:

- `sidebarGroups`, `sidebarTabs`, `mobileNavOpen`, `navIconMap`, and `data-mobile-row-card` are defined before later tasks rely on them.

# Spec: UI/UX 操作与组件一致性 — 2026-08-23

> 位置: `frontend/src/views/admin/`、`frontend/src/views/ResumeView.vue`、`frontend/src/layouts/AuthenticatedLayout.vue`、`frontend/src/components/SiteHeader.vue`、`frontend/src/components/business/`
> 类型: 前端用户体验、交互逻辑、响应式布局、可访问性与设计系统收敛
> 日期: 2026-08-23
> 状态: 待实施
> 审计依据: `.tech-audit/work/2026-08-23/report.md`（D15 UX & interaction / D16 UI & design-system craft）
> 原则: 先统一高风险操作语义与错误反馈，再收敛响应式和组件视觉；不引入新的业务能力，不改变后端数据口径

## 背景

本轮 UI/UX 审查没有发现安全级或 ship-blocker 问题，但发现多个页面对同一类用户行为采用了不同规则：

| 问题类别 | 当前现象 | 用户影响 |
|---|---|---|
| 破坏性操作 | 普通刷题题单删除有确认；代码题单删除和评测取消直接执行 | 用户误点后可能立即删除题单或终止评测 |
| 加载错误 | 简历或代码题单请求失败后被设置为空值 | 网络错误被误解为“没有简历/没有题单” |
| 移动端布局 | 进行中的评测使用 `min-w-[960px]` 横向表格 | 详情和取消入口在小屏被推到视口外 |
| 可访问性 | 折叠侧栏账户入口只有头像；分类输入只有 placeholder | 键盘、读屏和放大字号用户缺少稳定语义 |
| 组件一致性 | 原生 `select`、内联 SVG 与 shadcn/Lucide 并存 | 焦点态、暗色态、主题调整和维护方式不一致 |
| 图表主题 | 图表组件重复硬编码 porcelain 色阶 | 主题或品牌调整需要多处手工同步 |

这些问题共同指向一个核心缺口：系统缺少跨页面共享的“操作语义契约”。本 spec 将这些问题收敛为两条可独立交付的工作线：

- **M46：操作与状态一致性**：确认、错误/空状态、账户入口、表单 label、移动端关键操作。
- **M47：组件与视觉一致性**：图表 token、Select、Lucide 图标。

## 目标

- 所有删除、取消、终止类操作遵循同一套确认、loading、成功和失败反馈规则。
- 加载失败不再伪装成空数据；用户能看到失败原因并立即重试。
- 移动端用户无需横向滚动即可看到活动评测的核心状态和操作入口。
- 图标、下拉框、图表颜色和输入字段名称遵循项目现有约定。
- 保持现有业务行为、API、数据结构和路由不变，只改善交互表达与实现一致性。

## 非目标

- 不重做评测中心的信息架构，不新增评测状态或业务操作。
- 不修改删除、取消接口的后端语义，不增加撤销能力。
- 不把所有原生 HTML 控件机械替换为 shadcn；文件上传、文本域等保留原生语义的控件不在本轮强制迁移范围。
- 不引入新的 UI 框架、图标库、状态管理库或主题系统。
- 不以截图像素匹配作为验收标准；使用行为、文本、ARIA 语义和 viewport 下的元素可达性断言。

## 统一交互契约

### 1. 破坏性操作确认契约

以下操作必须在请求发出前经过确认：

| 操作 | 页面/入口 | 确认标题 | 确认说明要求 |
|---|---|---|---|
| 取消实验 | `EvaluationExperimentsView`、`EvaluationExperimentView` | 确认取消评测实验 | 说明已开始的实验会被终止 |
| 取消运行 | `EvaluationRunView` | 确认取消评测 | 说明当前运行及未完成 Case 的影响 |
| 删除代码题单 | `SiteHeader` | 确认删除题单 | 显示题单名称，并说明题目本身是否保留 |

实现规则：

1. 统一使用 `useConfirm` / `ConfirmDialog`，不使用浏览器原生 `confirm()`。
2. 用户选择取消时不发请求、不改变当前数据、不关闭当前工作区。
3. 用户确认后立即进入 in-flight 状态；同一对象的操作按钮禁用，避免重复请求。
4. 请求成功后刷新当前数据并给出成功 toast；请求失败保留当前页面和数据，并显示可读错误。
5. 确认文案使用业务语言，不暴露 API 名称、内部 ID 或实现术语。

### 2. 异步数据状态契约

简历和代码题单等主数据必须区分以下状态：

```text
idle → loading → success(data)
                 ├→ success(empty)
                 └→ error(previousData?)
```

具体规则：

- 首次加载失败：显示错误面板和“重试”，不能显示“尚未上传”或“没有题单”。
- 已有数据刷新失败：保留最后一次有效数据，在内容区域显示非阻塞错误提示和“重试”。
- 只有服务端明确返回无数据时，才显示空状态文案。
- 重试按钮复用同一加载函数，不能要求用户刷新整页或重新进入路由。
- 加载状态和错误状态应有稳定的 `data-testid`，便于 E2E 断言。

### 3. 紧凑账户入口契约

`UserMenu` 的 compact 模式必须具备完整按钮语义：

- 根元素为 `button type="button"`。
- 有稳定 accessible name，例如“账户菜单”。
- 包含 `aria-haspopup="menu"` 和随状态更新的 `aria-expanded`。
- 菜单打开后支持 `Escape` 关闭，关闭后焦点回到触发按钮。
- 折叠侧栏提供 `AppTooltip` 或同等可见提示，提示文字与 accessible name 保持一致。
- 下拉菜单中的操作项保持现有“审核题库 / 设置 / 退出登录”顺序，不改变业务权限。

### 4. 移动端活动评测契约

`EvaluationExperimentsView` 的活动实验区域按 breakpoint 提供两种表现：

- `md` 及以上：保留表格布局，保证列标题、状态、进度和操作对齐。
- `md` 以下：每个实验渲染为独立卡片，顺序固定为实验标识、评测对象、状态/进度、创建时间、操作。
- “详情”和“取消”必须在卡片可见区域内，不依赖横向滚动。
- 每个卡片继续保留稳定的 `data-testid="active-experiment-row-{id}"`，操作按钮使用稳定名称。
- 当没有活动实验时继续使用现有空状态；加载失败必须走异步数据状态契约。

### 5. 字段名称契约

`SettingsAdmin` 的大类和子类输入必须具备稳定可读名称：

- 大类输入：label 为“分类名称”。
- 子类输入：label 为“子分类名称”。
- label 可以使用 visually-hidden 样式，但不能仅依赖 placeholder。
- placeholder 只保留示例用途，不承担字段识别职责。
- 动态新增的每个输入均应有唯一关联 label 或 `aria-labelledby`。

## UI 组件与视觉契约

### 1. 图表 token

`PracticeStarChart` 和 `PracticeQuadChart` 不再直接持有 porcelain 色阶的 raw hex 值。

- 亮色/暗色基础色从 `frontend/src/utils/chartTokens.js` 的 `porcelain()`、`RAMP`、`RAMP_DARK` 获取。
- 轴线、网格、标签、tooltip 背景和边框优先复用已有 token；确需透明度时，在 token 层增加语义 token，不在组件内散落 `rgba(...)`。
- 组件内允许保留数据驱动的尺寸和布局计算，但颜色选择集中在共享 helper。
- 主题切换后，星图、四象限图和图例必须使用同一套亮暗色语义。

### 2. Select 组件

以下两个入口迁移到项目现有 shadcn Select：

- `frontend/src/views/admin/EvaluationReviewsView.vue` 的版本 A、版本 B、Case 选择。
- `frontend/src/components/business/PracticeDeckManager.vue` 的题目选择。

迁移规则：

- 使用 `Select`、`SelectTrigger`、`SelectValue`、`SelectContent`、`SelectItem`。
- 保持原有 `v-model` 和选择后的加载/加入题单行为不变。
- 遵守项目约定：`SelectItem` 不使用空字符串 value；无选择态使用稳定 sentinel，并在提交/请求前转换回业务空值。
- 保留字段 label、placeholder、禁用态和空列表说明。
- 验证键盘打开、上下选择、Enter 确认、Escape 关闭和暗色主题焦点态。

### 3. Lucide 图标

以下文件中的重复内联 SVG 迁移到项目已使用的 `@lucide/vue`：

- `frontend/src/components/business/UserMenu.vue`：展开箭头、审核、设置、退出登录。
- `frontend/src/components/business/QuestionCard.vue`：分享、编辑、收藏、展开、来源、加载和错误状态图标。

迁移规则：

- 保持现有图标含义和操作位置，不借机改变布局。
- 统一通过组件 `size`、`class` 和状态色表达尺寸、hover、disabled、loading。
- 图标作为纯装饰时设置 `aria-hidden`；图标按钮的 accessible name 由按钮 label 或 AppTooltip 提供。
- 不引入 `lucide-vue-next` 等第二套同义包，统一使用项目当前的 `@lucide/vue`。

## 实施计划

每个 Task 设计为可独立验证的小步骤；实现阶段必须遵循“先测试、后实现、再重构”的 TDD 顺序。

### M46：操作与状态一致性

**Files:**

- Edit: `frontend/src/views/admin/EvaluationExperimentsView.vue`
- Edit: `frontend/src/views/admin/EvaluationExperimentView.vue`
- Edit: `frontend/src/views/admin/EvaluationRunView.vue`
- Edit: `frontend/src/components/SiteHeader.vue`
- Edit: `frontend/src/views/ResumeView.vue`
- Edit: `frontend/src/layouts/AuthenticatedLayout.vue`
- Edit: `frontend/src/components/business/UserMenu.vue`
- Edit: `frontend/src/components/AppSidebar.vue`
- Edit: `frontend/src/components/business/SettingsAdmin.vue`
- Edit/Create test: `frontend/tests/e2e/uiux-operation-consistency.spec.js`

#### Task M46.1：统一评测取消确认

- [ ] 为实验列表取消按钮添加失败测试：点击取消后先出现确认对话框，未确认时 API 请求次数为 0。
- [ ] 为实验详情和运行详情复用同一失败测试矩阵，覆盖三个入口的标题、说明和取消按钮。
- [ ] 接入 `useConfirm`，确认后设置对应 in-flight 状态并调用现有取消 API。
- [ ] 补成功、失败、重复点击和取消确认分支断言。
- [ ] 运行 `cd frontend && npx playwright test tests/e2e/uiux-operation-consistency.spec.js`。

#### Task M46.2：统一代码题单删除确认

- [ ] 添加题单删除未确认不发请求的失败测试，并断言题单名称出现在确认文案中。
- [ ] 在 `SiteHeader.removePlaylist` 中接入 `useConfirm`，保留当前选中题单切换和成功 toast 行为。
- [ ] 添加删除失败时题单仍存在、错误提示可见的测试。
- [ ] 运行同一 E2E 文件中的题单删除场景。

#### Task M46.3：恢复真实异步状态

- [ ] 为 `ResumeView` mock 首次 `getResume` 失败，断言显示错误和重试，不显示“尚未上传简历”。
- [ ] 为 `AuthenticatedLayout` mock 题单请求失败，断言已有题单仍保留并出现重试入口。
- [ ] 将 `loadResume`、`loadOptimization`、`loadPositions` 和 `loadCodingPlaylists` 改为区分数据、loading、error 的状态。
- [ ] 验证重试成功后错误提示消失，空数据只在服务端明确返回空集合时出现。
- [ ] 运行 `cd frontend && npx playwright test tests/e2e/uiux-operation-consistency.spec.js`。

#### Task M46.4：账户入口与分类输入语义

- [ ] 添加 compact `UserMenu` 的键盘/ARIA 失败测试，覆盖 accessible name、`aria-expanded`、Escape 和焦点回归。
- [ ] 补齐 `UserMenu` 按钮语义和 compact tooltip，不改变菜单操作顺序。
- [ ] 为 SettingsAdmin 大类/子类输入增加 label，并用 locator 的 label 语义覆盖动态分类。
- [ ] 运行账户菜单和设置页面的 smoke/E2E 测试。

#### Task M46.5：活动评测移动卡片

- [ ] 添加 `390x844` viewport 测试，断言活动实验卡片中的详情和取消按钮可见且无需横向滚动。
- [ ] 在 `md` 以下实现卡片分支，桌面继续保留表格语义。
- [ ] 保持 `active-experiment-row-{id}` test id 和当前详情/取消行为。
- [ ] 运行 `cd frontend && npx playwright test tests/e2e/uiux-operation-consistency.spec.js --project=chromium`。

### M47：组件与视觉一致性

**Files:**

- Edit: `frontend/src/components/business/PracticeStarChart.vue`
- Edit: `frontend/src/components/business/PracticeQuadChart.vue`
- Edit: `frontend/src/utils/chartTokens.js`
- Edit: `frontend/src/views/admin/EvaluationReviewsView.vue`
- Edit: `frontend/src/components/business/PracticeDeckManager.vue`
- Edit: `frontend/src/components/business/UserMenu.vue`
- Edit: `frontend/src/components/business/QuestionCard.vue`
- Edit/Create test: `frontend/tests/e2e/uiux-component-consistency.spec.js`

#### Task M47.1：图表 token 收敛

- [ ] 添加静态检查，目标图表组件不再出现 porcelain 色阶 raw hex 或重复 tooltip 颜色配置。
- [ ] 将星图和四象限图的颜色读取收敛到 `chartTokens.js`。
- [ ] 必要时只在 token 文件增加语义化透明度 token，不在组件内新增散落颜色。
- [ ] 添加亮色/暗色主题下图例、轴线、节点和 tooltip 的 DOM/属性断言。
- [ ] 运行 `cd frontend && npm run lint` 和对应 smoke 测试。

#### Task M47.2：Select 组件收敛

- [ ] 为评测复核和题单管理添加键盘选择失败测试，覆盖 sentinel 空值和真实值转换。
- [ ] 将指定原生 `select` 替换为 shadcn Select，保持接口和业务事件不变。
- [ ] 验证空选项、长选项、禁用态、暗色主题和窄屏布局。
- [ ] 运行 `cd frontend && npx playwright test tests/e2e/uiux-component-consistency.spec.js`。

#### Task M47.3：内联 SVG 收敛

- [ ] 先为 UserMenu 和 QuestionCard 的关键按钮添加 accessible name 断言，防止图标迁移时丢失语义。
- [ ] 使用 `@lucide/vue` 替换指定重复 SVG，保持尺寸和交互状态。
- [ ] 对纯装饰图标设置 `aria-hidden`，对 loading/error 图标保留文本状态。
- [ ] 运行 `cd frontend && npm run lint`，并执行相关 smoke/E2E。

## 验收标准

### 行为与状态

- [ ] 三个评测取消入口和代码题单删除入口在确认前都不发请求。
- [ ] 取消确认后按钮进入 loading，重复点击不会产生重复请求。
- [ ] 删除/取消成功有成功反馈，失败有错误反馈且当前数据不被清空。
- [ ] 简历或题单请求失败时，页面不会显示误导性的空状态文案。
- [ ] 首次失败和已有数据刷新失败分别展示错误；两者都能通过重试恢复。

### 响应式与可达性

- [ ] `390x844`、`768x1024`、`1280x800` 三个 viewport 下，活动评测关键操作均可见。
- [ ] 移动端活动评测不要求横向滚动才能点击详情或取消。
- [ ] compact UserMenu 可通过键盘打开、Escape 关闭，焦点回到触发按钮。
- [ ] UserMenu、SettingsAdmin 输入和目标 Select 均有可读 accessible name。
- [ ] 现有 `frontend/tests/CLAUDE.md` 和 `frontend/tests/e2e/CLAUDE.md` 约束继续满足：API mock、无真实密码、禁止截图断言。

### 设计系统

- [ ] 两个目标图表的主题颜色全部来自共享 token/helper，亮色和暗色不会出现互相矛盾的颜色。
- [ ] 指定 Select 使用 shadcn 结构，空值使用 sentinel，不传空字符串给 `SelectItem`。
- [ ] UserMenu 和 QuestionCard 指定图标使用 `@lucide/vue`，不新增第二套图标库。
- [ ] 图标迁移不降低按钮 accessible name，不改变现有操作顺序和业务功能。

### 回归验证

- [ ] `cd frontend && npm run build` 通过。
- [ ] `cd frontend && npm run lint` 通过。
- [ ] `cd frontend && npx playwright test tests/e2e/uiux-operation-consistency.spec.js` 通过。
- [ ] `cd frontend && npx playwright test tests/e2e/uiux-component-consistency.spec.js` 通过。
- [ ] `cd frontend && npm test` 通过。
- [ ] `git diff --check` 通过，且没有把测试 mock 指向真实后端或提交真实凭据。

## 风险与控制

| 风险 | 影响 | 控制措施 |
|---|---|---|
| 确认框接入改变取消按钮时序 | 中 | 先锁定“未确认不发请求”的测试，再接入 `useConfirm` |
| 错误状态改造影响已有空状态 | 中 | 使用明确的 success-empty/error 分支，保留服务端返回空集合的原文案 |
| 移动卡片与桌面表格出现两套数据渲染逻辑 | 中 | 抽取共享行字段/操作组件，E2E 同时覆盖两个 breakpoint |
| Select sentinel 被错误提交给 API | 中 | 在 composable/view 边界统一转换，增加选择和提交断言 |
| 图标替换导致读屏名称丢失 | 低 | 先测按钮 accessible name，再替换图标；装饰图标显式 `aria-hidden` |
| 依赖未安装导致渲染级验证无法执行 | 中 | 释放磁盘后先执行 build/lint，再执行两个新增 E2E 文件和 smoke gate |

## 实施顺序与提交建议

1. `M46.1`：评测取消确认。
2. `M46.2`：代码题单删除确认。
3. `M46.3`：异步错误与空状态。
4. `M46.4`：账户入口与表单 label。
5. `M46.5`：活动评测移动卡片。
6. `M47.1`：图表 token。
7. `M47.2`：Select 组件。
8. `M47.3`：Lucide 图标。

每个 Task 完成后创建聚焦提交，建议提交信息：

- `fix(frontend): standardize destructive action confirmation`
- `fix(frontend): distinguish loading errors from empty states`
- `fix(frontend): make active evaluations responsive`
- `refactor(frontend): standardize chart and form components`
- `refactor(frontend): replace repeated inline svg icons`

## 完成定义

当 M46 与 M47 的验收项全部满足、两组新增 E2E 通过、build/lint/smoke gate 通过，并且在 `390x844` 和桌面 viewport 完成一次人工键盘走查后，本 spec 才可标记为已完成。任何因环境依赖未执行的验证都必须在 spec 或交付说明中明确列为未完成，不得用静态源码检查替代渲染级结论。

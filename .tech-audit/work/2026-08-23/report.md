# Deep audit — D15 UX & interaction / D16 UI & design-system craft — 2026-08-23

**Repo**: interview-boss · **Stack**: Vue 3 / Vite / TypeScript-JavaScript / Tailwind / shadcn-vue · **HEAD**: `030375bd`
**Findings source**: `.tech-audit/work/2026-08-23/findings.tsv`

本轮聚焦用户体验、错误与空状态、破坏性操作语义、移动端行为，以及 UI 组件和视觉 token 的统一性。源码级审查没有发现 🔴 ship-blocker；共有 8 条 🟡、1 条 🟢。其中“分类编辑输入缺少 label”和“内联 SVG 图标”在既有审查中已经出现，本轮确认当前 HEAD 仍未收敛。

## D15 — UX & interaction

**Status**: ⚠️ · **Findings**: 🔴 0 · 🟡 6 · 🟢 0

当前最大的体验风险不是单个控件，而是同一类操作在不同页面拥有不同的安全与反馈语义：刷题题单删除有确认，代码题单删除没有；简历删除有确认，但评测取消直接执行；数据请求失败又被映射为空状态。用户容易误判当前状态，或在不知情时触发不可逆操作。

### 🟡 Findings

| Finding | Suggested fix | Effort |
|---|---|---|
| `UserMenu.vue:4-22` / `AppSidebar.vue:166-178`：折叠侧栏账户入口只有头像，没有可访问名称和展开状态语义 | 补 `aria-label`、`aria-expanded`、`aria-haspopup`，并为 compact 状态提供统一 tooltip | 2h |
| `EvaluationExperimentsView.vue:146-156,451-452`、`EvaluationExperimentView.vue:74-85,121`、`EvaluationRunView.vue:119-125,213`：评测取消直接执行 | 统一接入 `useConfirm`，确认后再取消并保留并发禁用 | 4-6h |
| `SiteHeader.vue:98-107,186-190`：代码题单删除没有确认，而 `usePracticeDecks.deleteDeck` 有确认 | 复用全局确认对话框，文案说明题目是否保留 | 2h |
| `ResumeView.vue:44-71,213-220`、`AuthenticatedLayout.vue:182-190`：请求失败被显示成空状态 | 保留有效数据，区分 empty/error，提供重试 | 4-6h |
| `EvaluationExperimentsView.vue:415-457`：活动实验使用 `min-w-[960px]` 横向表格 | 移动端改为卡片行，保证详情和取消入口在首屏可达 | 1d；需浏览器复核 |
| `SettingsAdmin.vue:212-214,228-230`：分类输入只有 placeholder，没有稳定 label | 增加 visually-hidden label 或 aria-label | 2h |

## D16 — UI & design-system craft

**Status**: ⚠️ · **Findings**: 🔴 0 · 🟡 2 · 🟢 1

设计系统已经有共享的 porcelain 图表 token 和 shadcn 控件，但部分高频/管理界面仍绕过这些抽象。短期表现为视觉不一致，长期会让主题、暗色模式、焦点态和品牌调整出现多点漂移。

### 🟡 / 🟢 Findings

| Severity | Finding | Suggested fix | Effort |
|---|---|---|---|
| 🟡 | `PracticeStarChart.vue:47-103`、`PracticeQuadChart.vue:33-84` 重复硬编码图表色阶，绕过 `utils/chartTokens.js` | 统一使用 `porcelain`、`RAMP`、`RAMP_DARK` 和共享 tooltip helper | 4-6h |
| 🟡 | `EvaluationReviewsView.vue:231-233`、`PracticeDeckManager.vue:87-90` 仍使用手写样式原生 `select` | 可迁移的下拉控件统一为 shadcn Select，保留确有语义差异的原生控件 | 4-6h |
| 🟢 | `UserMenu.vue:18-79`、`QuestionCard.vue:24-124` 仍内联多组 SVG，与 lucide 图标体系并存 | 替换为 lucide-vue 组件，统一尺寸、stroke 和状态色 | 1d |

## Triage — proposed milestones

脚本化 triage 已按项目现有 `M<N>` 命名规则运行；由于本轮没有 🔴，工具将 🟡 按维度分组。建议落成两个连续里程碑：

| Milestone | Scope | Suggested target |
|---|---|---|
| **M46-uiux-operation-consistency** | D15：取消/删除确认、加载失败与空状态、账户入口可访问语义、设置输入 label | `frontend/src/views/admin/`、`frontend/src/views/ResumeView.vue`、`frontend/src/components/SiteHeader.vue`、`frontend/src/components/business/SettingsAdmin.vue` |
| **M47-uiux-component-consistency** | D15/D16：活动实验移动卡片、图表 token、Select 与图标统一 | `frontend/src/views/admin/EvaluationExperimentsView.vue`、`frontend/src/components/business/Practice*Chart.vue`、`frontend/src/views/admin/EvaluationReviewsView.vue` |

## Verification boundary

- `git diff --check`: 通过。
- `node --check frontend/src/composables/usePracticeDecks.js frontend/src/utils/chartTokens.js`: 通过。
- `npm run build`: 未能启动，`vite` 不存在。
- `npm run lint`: 未能启动，`eslint` 不存在。
- `npm ci --ignore-scripts`: 因磁盘 `ENOSPC` 失败；当前文件系统使用率为 100%，因此本轮未执行 Playwright/浏览器渲染级复核。

因此，除标记为 `needs-verification` 的移动端表格外，其余 findings 均来自已逐段读取的源码路径；“视觉实际效果”和“不同 viewport 的可达性”仍应在释放磁盘、恢复依赖后补跑质量门禁与响应式 E2E。

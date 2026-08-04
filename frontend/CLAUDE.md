# Frontend — InterviewBoss

> 位置：`frontend/` | 上游：`backend/` 提供 API | 部署：构建产物由 nginx 服务
> 职责：Vue 3 单页应用，Vue Router 4 路由 + Composition API + composables 架构。

## 命令

```bash
cd frontend
npm run dev          # 开发服务器 http://localhost:3000
npm run build        # 生产构建 → frontend/dist（Docker nginx-runtime 会内置该目录）
npm run test         # 日常 smoke 测试（Playwright 自动启动 Vite）
npm run test:e2e     # 运行完整 E2E 测试
npm run audit:prod   # 生产依赖 audit 报告
```

`./deploy/docker-deploy.sh check frontend` 会执行 `npm run build` 和 `npm run test`；`./deploy/docker-deploy.sh check audit` 会汇总 npm/pip audit，但第一阶段只报告不拦截。

## 技术栈

Vue 3 (Composition API) / Vue Router 4 / Vite / Tailwind CSS / shadcn-vue (reka-ui) / ECharts / Marked + DOMPurify / vue-sonner / vue-virtual-scroller

## UI 方向

- 全面采用 shadcn-vue 组件（reka-vega 风格），禁止手写自定义 UI 组件类
- Button/Card/Badge/Dialog/Select/Table/AlertDialog/Skeleton 等一律使用 shadcn 组件
- 图标统一使用 `@lucide/vue`，禁止内联 SVG
- 悬停提示统一使用 `components/common/AppTooltip.vue`（底层 shadcn Tooltip），不要新增原生 `title` 或自定义 tooltip 气泡；全局 `TooltipProvider` 放在 `App.vue`
- global.css 仅保留全局基础样式（reset、scrollbar、prose-chat、elevation、动画），不包含组件样式
- 通用组件在 `components/common/`，shadcn 原始组件在 `components/ui/`

### UI 一致性基线

- 页面边距统一优先使用 `px-4 py-4 md:px-6 md:py-6`，模块间距由父容器 `gap-*` 管理，子组件避免自带 `mb-*`。
- 主卡片、列表容器、图表容器统一优先使用 `rounded-xl border border-border bg-card shadow-sm`。
- toolbar/filter 区统一优先使用 `rounded-xl border border-border bg-card p-3`；内部控件不再各自包一层重边框卡片。
- 数据表外壳必须自己承担圆角裁切和宽度约束：`rounded-xl border border-border bg-card shadow-sm overflow-hidden w-full min-w-0`，避免背景线条破坏圆角或横向溢出。
- 文本型数据表在 `md` 以下必须提供卡片式行视图，避免把表格列压缩成竖排文本；优先复用 `components/common/DataTable.vue` 的移动卡片行为。
- 认证壳导航由 `AuthenticatedLayout.vue` 的 `sidebarGroups` 作为单一数据源，桌面侧栏和移动导航必须保持同序、同标签、同计数。
- 侧栏展开态的品牌 logo/InterviewBoss 文案始终导航回 `/master-bank`；侧栏折叠/展开动作必须使用独立图标按钮，不要把品牌入口改成折叠开关。
- Chat/Coding 这类带内部侧栏的工作台在移动端使用 overlay/toggle，不要让侧栏常驻挤压主内容。
- Chat 流式回复的思考区使用 `ReasoningTimeline.vue`：发送开始即用前端本地计时器显示“思考中 N 秒”，收到后端 `thinking_done.duration` 后显示“思考了 N 秒”。不要只等最终 SSE duration 才展示时间。
- Chat 流式发送必须为每个请求保存独立的 `client_request_id`、`turn_id` 和 AbortController；停止时先调用当前 turn 的 cancel API，再只 abort 当前 SSE，不得在 ChatView 中调用全局 `cancelAllRequests()`，取消/冲突/AbortError 也不得追加伪造 assistant 消息。
- 普通按钮、输入框、Select、Dialog、Badge 优先使用 shadcn 默认组件圆角，不额外覆盖圆角；确需覆盖时同一组件组内保持一致。
- reka-ui `SelectItem` 不允许空字符串 value；“全部/未提供/不选择”等空业务值必须用 `__all__`/`__empty__`/`__none__` 等内部哨兵，emit 或保存时再转回空字符串/null。
- 交互行/列表项使用 `rounded-lg`，内容内嵌块使用 `rounded-md`，进度条和开关保留 `rounded-full`。
- 业务弹窗只做视觉统一时，外壳统一 `rounded-xl border border-border bg-card shadow-lg`，内部边界统一 `border-border` 或 `border-border/50`。

## 目录结构

```
src/
├── App.vue           ← 薄路由壳（~16 行，只有 <router-view> + <Toaster>）
├── router/
│   └── index.js      ← Vue Router 配置（路由表 + 认证守卫）
├── layouts/
│   ├── AuthenticatedLayout.vue ← 已登录布局（数据层：调用 composables + provide/inject + 侧边栏 + 全局模态框）
│   ├── DefaultLayout.vue       ← 默认布局（min-h-screen + 背景色，支持 light/dark）
│   └── BlankLayout.vue         ← 无侧边栏布局（登录页）
├── views/            ← 页面组件（inject('appData') 获取共享数据）
│   ├── MasterBankView.vue
│   ├── ChatView.vue
│   ├── JdView.vue
│   ├── InterviewView.vue
│   ├── MockInterviewView.vue
│   ├── InsightsView.vue       ← 洞察总览/岗位准备度/面试复盘三路由共用编排视图
│   ├── KnowledgeGraphView.vue ← 旧入口兼容保留
│   ├── ImportView.vue
│   ├── CodingView.vue
│   ├── SettingsView.vue
│   └── LoginView.vue
├── services/         ← API 服务层（按领域拆分），http.js 是 HTTP 客户端
├── api/index.js      ← 统一 re-export（兼容旧 import）
├── composables/      ← 领域逻辑（use* 前缀）
├── components/
│   ├── common/       ← 通用 UI（无业务依赖）
│   ├── business/     ← 业务组件
│   ├── ui/           ← shadcn-vue 原始组件
│   └── *.vue         ← 应用壳层组件（AppSidebar / NavMain / NavUser / NavDocuments / NavSecondary / SiteHeader / ChartAreaInteractive / DashboardDataTable / DraggableRow / DragHandle）
├── utils/            ← 纯工具函数
├── constants/        ← config.js、enums.js
├── stores/           ← Pinia 状态层（当前为空，状态走 composables）
├── lib/              ← shadcn-vue 工具函数（gitignored，不提交）
└── assets/styles/    ← CSS 变量、重置、全局样式 + Tailwind
```

**路径别名：** `@/` → `src/`，跨模块依赖统一用 `@/` 绝对路径。

## 代码路由表

| 功能 | 路由 | View 组件 | 数据源 |
|------|------|----------|--------|
| 高频题库 | `/master-bank` | `views/MasterBankView.vue` | `composables/useMasterBankData.js` |
| 模拟面试 | `/chat` | `views/ChatView.vue` | `components/business/ChatView.vue` |
| JD 筛选 | `/jd` | `views/JdView.vue` | `composables/useMasterBankData.js` |
| 面经库 | `/interview` | `views/InterviewView.vue` | `composables/useMasterBankData.js` |
| 题目抽测 | `/mock-interview` | `views/MockInterviewView.vue` | `components/business/MockInterview.vue` |
| 刷题 | `/practice` | `views/PracticeView.vue` | `components/business/PracticeMode.vue` |
| 洞察总览 | `/insights/overview` | `views/InsightsView.vue` | `composables/useInsightsData.js` + `services/insightsApi.js` |
| 岗位准备度 | `/insights/readiness` | `views/InsightsView.vue` | `components/business/InsightsReadiness.vue` |
| 面试复盘 | `/insights/reviews` | `views/InsightsView.vue` | `components/business/InsightsReviews.vue` |
| 知识图谱（兼容入口） | `/knowledge-graph` | 重定向到 `/insights/readiness?view=graph` | `components/business/KnowledgeGraph.vue` |
| 导入 | `/import` | `views/ImportView.vue` | `components/business/StagingPanel.vue` |
| 手撕代码 | `/coding` | `views/CodingView.vue` | `components/business/CodingPractice.vue` |
| 设置 | `/settings` | `views/SettingsView.vue` | `components/business/SettingsPage.vue` |
| 登录 | `/login` | `views/LoginView.vue` | `composables/useAuth.js` |

**数据流：** AuthenticatedLayout 调用 composables → `provide('appData')` → View 组件 `inject('appData')` 获取共享数据。业务组件优先消费共享数据；局部动作可调用 `services/` 或兼容层 `api/index.js`，但不要直接 `fetch`。

| 功能 | 文件 |
|------|------|
| 路由配置 + 守卫 | `router/index.js` |
| 认证状态（单例） | `composables/useAuth.js`（`currentUser` 模块级 ref） |
| 题库数据 + 筛选 | `composables/useMasterBankData.js`（`bankFilter`: all/public/mine 三口径） |
| 题库重建 | `composables/useBuildTrigger.js` |
| 题目操作 | `composables/useQuestionOps.js` + `services/masterBankApi.js` |
| 批量操作 | `composables/useBatchActions.js` |
| 合并弹窗 | `composables/useMergeDialog.js` |
| 练习/面试 | `composables/usePractice.js` + `services/practiceApi.js` + `views/PracticeView.vue` + `components/business/PracticeMode.vue` + `components/business/PracticePanel.vue` |
| 导入任务 | `composables/useSubmitJobs.js` + `services/dataApi.js` |
| 数据分析 | `services/analyticsApi.js` + `components/business/AnalyticsSidebar.vue` |
| 用户配置 | `services/profileApi.js` + `components/business/SettingsPage.vue` |
| 模拟面试 | `services/interviewApi.js` + `components/business/MockInterview.vue` |
| 面试分布 | `services/interviewDistributionApi.js` + `components/business/InterviewDistributionSettings.vue` |
| 简历管理 | `services/resumeApi.js` |
| 多选 | `composables/useSelection.js` |
| 侧边栏 | `composables/useSidebar.js` |
| 导航高亮 | `composables/useHighlightNav.js` |
| Tab 滚动 | `composables/useTabScroll.js` |
| 主题切换 | `composables/useTheme.js` |
| 通知 | `composables/useNotification.js` |
| 动画 | `composables/useMotionPresets.js` |
| HTTP 客户端 | `services/http.js`（`api/index.js` 是 re-export 兼容层） |

## 岗位设置注意事项

- `services/profileApi.js` 的岗位增删会主动失效 `/api/positions` 缓存，`fetchPositions()` 默认绕过 GET TTL，避免软删除后设置页看到旧岗位。
- 设置页切换岗位后必须同步 `currentUser.current_position` 并触发 `loadAllData()`，否则跨 tab 数据和设置页高亮会停留在旧岗位。

## 修改前必读

| 你要做的事 | 先读这些文件 | 再读这些文件 |
|-----------|------------|------------|
| 改路由/导航/守卫 | `router/index.js` | `layouts/AuthenticatedLayout.vue` |
| 改数据层/composables | `layouts/AuthenticatedLayout.vue` | 对应 composable |
| 改登录/登出/token | `composables/useAuth.js`（单例） | `services/authApi.js` + `services/http.js` |
| 改某个页面 | `views/XxxView.vue` | 对应 `components/business/*.vue` |
| 改 Chat 流式消息/思考计时 | `components/business/ChatView.vue` | `components/business/ReasoningTimeline.vue` + `services/chatApi.js` |
| 改侧边栏导航 | `components/AppSidebar.vue` | `layouts/AuthenticatedLayout.vue` |
| 新增页面 | 创建 `views/XxxView.vue` + 在 `router/index.js` 添加路由 | 在 `AuthenticatedLayout.vue` 的 provide 中添加需要的数据 |

## 认证

Access Token 存内存（不存 localStorage）。Refresh Token 存 HttpOnly Cookie。401 时 `http.js` 自动刷新重试。

## 详细规则

Vue 组件规范、composables 规范和测试规则见 `.claude/rules/`：
- `vue-components.md` — 编辑 Vue 文件时自动加载
- `vue-composables.md` — 编辑 composables 文件时自动加载
- `test-files.md` — 编辑测试文件时自动加载

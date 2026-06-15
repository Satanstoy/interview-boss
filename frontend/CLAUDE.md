# Frontend — InterviewBoss

> 位置：`frontend/` | 上游：`backend/` 提供 API | 部署：构建产物由 nginx 服务
> 职责：Vue 3 单页应用，Vue Router 4 路由 + Composition API + composables 架构。

## 命令

```bash
cd frontend
npm run dev          # 开发服务器 http://localhost:3000
npm run build        # 生产构建 → /var/www/interview-boss/dist/
npx playwright test  # 运行 E2E 测试
```

## 技术栈

Vue 3 (Composition API) / Vue Router 4 / Vite / Tailwind CSS / ECharts / Marked + DOMPurify / vue-sonner / vue-virtual-scroller

## UI 方向

- 全面采用 shadcn-vue 组件（reka-vega 风格），禁止手写自定义 UI 组件类
- Button/Card/Badge/Dialog/Select/Table/AlertDialog/Skeleton 等一律使用 shadcn 组件
- 图标统一使用 `@lucide/vue`，禁止内联 SVG
- global.css 仅保留全局基础样式（reset、scrollbar、prose-chat、elevation、动画），不包含组件样式
- 通用组件在 `components/common/`，shadcn 原始组件在 `components/ui/`

## 目录结构

```
src/
├── App.vue           ← 薄路由壳（~16 行，只有 <router-view> + <Toaster>）
├── router/
│   └── index.js      ← Vue Router 配置（路由表 + 认证守卫）
├── layouts/
│   ├── AuthenticatedLayout.vue ← 已登录布局（数据层：调用 composables + provide/inject + 侧边栏 + 全局模态框）
│   └── BlankLayout.vue         ← 无侧边栏布局（登录页）
├── views/            ← 页面组件（inject('appData') 获取共享数据）
│   ├── MasterBankView.vue
│   ├── ChatView.vue
│   ├── JdView.vue
│   ├── InterviewView.vue
│   ├── MockInterviewView.vue
│   ├── KnowledgeGraphView.vue
│   ├── ImportView.vue
│   ├── CodingView.vue
│   ├── SettingsView.vue
│   └── LoginView.vue
├── services/         ← API 服务层（按领域拆分），http.js 是 HTTP 客户端
├── api/index.js      ← 统一 re-export（兼容旧 import）
├── composables/      ← 领域逻辑（use* 前缀）
├── components/
│   ├── common/       ← 通用 UI（无业务依赖）
│   └── business/     ← 业务组件
├── utils/            ← 纯工具函数
├── constants/        ← config.js、enums.js
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
| 知识图谱 | `/knowledge-graph` | `views/KnowledgeGraphView.vue` | `components/business/KnowledgeGraph.vue` |
| 导入 | `/import` | `views/ImportView.vue` | `components/business/StagingPanel.vue` |
| 手撕代码 | `/coding` | `views/CodingView.vue` | `components/business/CodingPractice.vue` |
| 设置 | `/settings` | `views/SettingsView.vue` | `components/business/SettingsPage.vue` |
| 登录 | `/login` | `views/LoginView.vue` | `composables/useAuth.js` |

**数据流：** AuthenticatedLayout 调用 composables → `provide('appData')` → View 组件 `inject('appData')` 获取共享数据。

| 功能 | 文件 |
|------|------|
| 路由配置 + 守卫 | `router/index.js` |
| 认证状态（单例） | `composables/useAuth.js`（`currentUser` 模块级 ref） |
| 题库数据 + 筛选 | `composables/useMasterBankData.js` |
| 题库重建 | `composables/useBuildTrigger.js` |
| 题目操作 | `composables/useQuestionOps.js` + `services/masterBankApi.js` |
| 练习/面试 | `services/practiceApi.js` + `components/business/PracticePanel.vue` |
| 数据分析 | `services/analyticsApi.js` + `components/business/AnalyticsSidebar.vue` |
| 用户配置 | `services/profileApi.js` + `components/business/SettingsPage.vue` |
| HTTP 客户端 | `services/http.js`（`api/index.js` 是 re-export 兼容层） |

## 修改前必读

| 你要做的事 | 先读这些文件 | 再读这些文件 |
|-----------|------------|------------|
| 改路由/导航/守卫 | `router/index.js` | `layouts/AuthenticatedLayout.vue` |
| 改数据层/composables | `layouts/AuthenticatedLayout.vue` | 对应 composable |
| 改登录/登出/token | `composables/useAuth.js`（单例） | `services/authApi.js` + `services/http.js` |
| 改某个页面 | `views/XxxView.vue` | 对应 `components/business/*.vue` |
| 改侧边栏导航 | `components/AppSidebar.vue` | `layouts/AuthenticatedLayout.vue` |
| 新增页面 | 创建 `views/XxxView.vue` + 在 `router/index.js` 添加路由 | 在 `AuthenticatedLayout.vue` 的 provide 中添加需要的数据 |

## 认证

Access Token 存内存（不存 localStorage）。Refresh Token 存 HttpOnly Cookie。401 时 `http.js` 自动刷新重试。

## 详细规则

Vue 组件规范、composables 规范和测试规则见 `.claude/rules/`：
- `vue-components.md` — 编辑 Vue 文件时自动加载
- `vue-composables.md` — 编辑 composables 文件时自动加载
- `test-files.md` — 编辑测试文件时自动加载

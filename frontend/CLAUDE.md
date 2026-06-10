# Frontend — InterviewBoss

> 位置：`frontend/` | 上游：`backend/` 提供 API | 部署：构建产物由 nginx 服务
> 职责：Vue 3 单页应用，Composition API + composables 架构。

## 命令

```bash
cd frontend
npm run dev          # 开发服务器 http://localhost:3000
npm run build        # 生产构建 → /var/www/interview-boss/dist/
npx playwright test  # 运行 E2E 测试
```

## 技术栈

Vue 3 (Composition API) / Vite / Tailwind CSS / ECharts / Marked + DOMPurify / vue-sonner / vue-virtual-scroller

## UI 方向

- 全面采用 shadcn-vue 组件（reka-vega 风格），禁止手写自定义 UI 组件类
- Button/Card/Badge/Dialog/Select/Table/AlertDialog/Skeleton 等一律使用 shadcn 组件
- 图标统一使用 `@lucide/vue`，禁止内联 SVG
- global.css 仅保留全局基础样式（reset、scrollbar、prose-chat、elevation、动画），不包含组件样式
- 通用组件在 `components/common/`，shadcn 原始组件在 `components/ui/`

## 目录结构

```
src/
├── App.vue           ← 纯编排层（组合 composables、转发事件、Tab 切换）
├── services/         ← API 服务层（按领域拆分），http.js 是 HTTP 客户端
├── api/index.js      ← 统一 re-export（兼容旧 import）
├── composables/      ← 领域逻辑（use* 前缀）
├── components/
│   ├── common/       ← 通用 UI（无业务依赖）
│   └── business/     ← 业务组件
├── utils/            ← 纯工具函数
├── constants/        ← config.js、enums.js
├── layouts/          ← 布局组件（DefaultLayout、BlankLayout）
└── assets/styles/    ← CSS 变量、重置、全局样式 + Tailwind
```

**路径别名：** `@/` → `src/`，跨模块依赖统一用 `@/` 绝对路径。

## 代码路由表

| 功能 | 文件 |
|------|------|
| 认证状态 | `composables/useAuth.js` |
| 题库数据 + 筛选 | `composables/useMasterBankData.js` |
| 题库重建 | `composables/useBuildTrigger.js` |
| 题目操作 | `composables/useQuestionOps.js` + `services/masterBankApi.js` |
| 练习/面试 | `services/practiceApi.js` + `components/business/PracticePanel.vue` |
| 数据分析 | `services/analyticsApi.js` + `components/business/AnalyticsSidebar.vue` |
| 用户配置 | `services/profileApi.js` + `components/business/SettingsPage.vue` |
| 个人中心 | `components/business/SettingsPage.vue`（个人信息、面试偏好、AI 配置、账户安全） |
| 考点分布 | `components/business/ExamDistribution.vue`（高频题库页面） |
| HTTP 客户端 | `services/http.js`（`api/index.js` 是 re-export 兼容层） |

## 修改前必读

| 你要做的事 | 先读这些文件 | 再读这些文件 |
|-----------|------------|------------|
| 改登录/登出/token | `composables/useAuth.js` | `services/authApi.js` + `services/http.js` |
| 改题库数据/筛选 | `composables/useMasterBankData.js` | `services/masterBankApi.js` |
| 改题库重建 | `composables/useBuildTrigger.js` | `services/masterBankApi.js` |
| 改题目操作 | `composables/useQuestionOps.js` | `components/business/MasterBankList.vue` |
| 改练习/面试 | `services/practiceApi.js` | `components/business/PracticePanel.vue` + `MockInterview.vue` |
| 改数据分析 | `services/analyticsApi.js` | `components/business/AnalyticsSidebar.vue` |
| 改用户配置 | `services/profileApi.js` | `components/business/SettingsPage.vue` |
| 改 App.vue 编排 | `App.vue` | 对应的 composable 或 component |
| 新增页面/Tab | `App.vue`（Tab 切换逻辑） | 新建 `components/business/*.vue` + 对应 composable |

## 认证

Access Token 存内存（不存 localStorage）。Refresh Token 存 HttpOnly Cookie。401 时 `http.js` 自动刷新重试。

## 详细规则

Vue 组件规范、composables 规范和测试规则见 `.claude/rules/`：
- `vue-components.md` — 编辑 Vue 文件时自动加载
- `vue-composables.md` — 编辑 composables 文件时自动加载
- `test-files.md` — 编辑测试文件时自动加载

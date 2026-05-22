# Frontend — InterviewBoss

Vue 3 + Vite 前端。此文件补充根目录 CLAUDE.md。

## 命令

```bash
cd frontend
npm run dev          # 开发服务器 http://localhost:3000
npm run build        # 生产构建 → /var/www/interview-boss/dist/
npx playwright test  # 运行 E2E 测试
```

## 技术栈

Vue 3 (Composition API) / Vite / Tailwind CSS / ECharts / Marked + DOMPurify / vue-sonner / vue-virtual-scroller

## 目录结构

```
src/
├── App.vue           ← 核心编排（数据、认证、筛选状态）
├── services/         ← API 服务层（按领域拆分），http.js 是 HTTP 客户端
├── api/index.js      ← 统一 re-export（兼容旧 import）
├── composables/      ← 领域逻辑复用（use* 前缀）
├── components/
│   ├── common/       ← 通用 UI（无业务依赖）
│   └── business/     ← 业务组件
├── utils/            ← 纯工具函数
├── assets/styles/    ← CSS 变量、重置、全局样式 + Tailwind
├── layouts/          ← 布局组件（DefaultLayout、BlankLayout）
├── constants/        ← config.js、enums.js
├── router/           ← 路由占位（当前未使用 Vue Router）
├── stores/           ← Pinia store 占位（当前状态在 App.vue）
└── views/            ← 页面视图占位（当前 Tab 切换）
```

**路径别名：** `@/` → `src/`，跨模块依赖统一用 `@/` 绝对路径。

## TDD 工作流（强制）

**任何修 Bug 或新功能，必须按以下顺序执行：**

1. **先写测试（红灯）** — 在 `frontend/tests/` 中写 Playwright 测试，运行确认失败
2. **最小实现（绿灯）** — 只写让测试通过的最少代码
3. **重构** — 测试通过后优化代码，每次改动后重跑测试

## 代码路由表

| 功能 | 文件 |
|------|------|
| 认证逻辑 | `services/authApi.js` + `services/http.js` |
| 题库操作 | `services/masterBankApi.js` + `components/business/MasterBankList.vue` |
| 练习/面试 | `services/practiceApi.js` + `components/business/PracticePanel.vue` |
| 数据分析 | `services/analyticsApi.js` + `components/business/AnalyticsSidebar.vue` |
| 用户配置 | `services/profileApi.js` + `components/business/SettingsPanel.vue` |
| 通用 UI | `components/common/`（DataTable、TabBar、PaginationBar 等） |
| 业务逻辑复用 | `composables/`（use* 前缀） |

## 修改前必读（避免盲目搜索）

| 你要做的事 | 先读这些文件 | 再读这些文件 |
|-----------|------------|------------|
| 修登录 Bug | `services/authApi.js` + `services/http.js` | `components/business/LoginModal.vue` |
| 改题库列表 | `services/masterBankApi.js` | `components/business/MasterBankList.vue` |
| 改练习/面试 | `services/practiceApi.js` | `components/business/PracticePanel.vue` + `MockInterview.vue` |
| 改数据分析 | `services/analyticsApi.js` | `components/business/AnalyticsSidebar.vue` |
| 改用户配置 | `services/profileApi.js` | `components/business/SettingsPanel.vue` |
| 改通用 UI 组件 | `components/common/` 对应文件 | `App.vue`（看怎么被调用） |
| 改业务逻辑复用 | `composables/use*.js` | 调用它的 `components/business/*.vue` |
| 改 HTTP 客户端 | `services/http.js` | `api/index.js`（re-export） |
| 新增页面/Tab | `App.vue`（Tab 切换逻辑） | 新建 `components/business/*.vue` |

## 认证

Access Token 存内存（不存 localStorage）。Refresh Token 存 HttpOnly Cookie。401 时 `http.js` 自动刷新重试。

## 详细规则

Vue 组件规范、composables 规范和测试规则见 `.claude/rules/`：
- `vue-components.md` — 编辑 Vue 文件时自动加载
- `vue-composables.md` — 编辑 composables 文件时自动加载
- `test-files.md` — 编辑测试文件时自动加载

## 修改铁律

1. **修改后必须更新 CLAUDE.md** — 涉及文件增删、职责变更时，更新对应目录的 CLAUDE.md
2. **一组修改必须 commit** — 逻辑相关修改完成后立即提交
3. **新模块必须更新 README** — 新增功能后更新 README.md

子目录 CLAUDE.md 位置：`src/components/business/`、`src/components/common/`、`src/services/`、`src/composables/`、`src/utils/`、`tests/`。

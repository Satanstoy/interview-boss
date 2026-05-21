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

### 1. 先写测试（红灯）

在 `frontend/tests/` 中写 Playwright 测试，运行确认**失败**。

### 2. 最小实现（绿灯）

只写让测试通过的**最少代码**。运行确认**通过**。

### 3. 重构

测试通过后优化代码，每次改动后重新运行测试确认仍通过。

## 测试规则

- 框架：Playwright（`@playwright/test`）
- 测试目录：`frontend/tests/`
- 测试必须 mock API 响应，**禁止调用真实后端**
- 命名：`test-<场景>.spec.ts`

### 禁止截图测试

**禁止使用 `page.screenshot()`、`expect(page).toHaveScreenshot()` 等截图断言。** 部分模型无法处理图片，截图测试会导致测试无法被 AI 理解和调试。

### 推荐的断言方式

```typescript
// ✅ 正确：基于文本/元素的断言
await expect(page.getByText('登录成功')).toBeVisible()
await expect(page.getByRole('button', { name: '提交' })).toBeEnabled()
await expect(page.locator('[data-testid="question-list"]')).toHaveCount(5)

// ✅ 正确：基于 URL 的断言
await expect(page).toHaveURL(/.*dashboard/)

// ✅ 正确：Mock API 响应
await page.route('**/api/data/*', route =>
  route.fulfill({ status: 200, body: JSON.stringify(mockData) })
)

// ❌ 禁止：截图断言
// await expect(page).toHaveScreenshot()
// await page.screenshot({ path: 'test.png' })
```

## Vue 3 规则

- `<script setup>` only，禁止 Options API、mixins
- Composables 命名 `use*`，返回 refs，不含渲染逻辑
- `ref` 用于基本类型；`reactive` 仅用于固定结构对象，禁止解构
- Props 只读，子传父用 emit 事件
- 命名导出（named export），禁止 default export
- 通用组件（`common/`）禁止引入 API 或业务逻辑

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

## 认证

Access Token 存内存（不存 localStorage）。Refresh Token 存 HttpOnly Cookie。401 时 `http.js` 自动刷新重试。

## 禁止

- `any` 类型
- 组件内直接 fetch（用 `services/` + `composables/`）
- `common/` 组件引入业务依赖
- 截图测试（`page.screenshot()`、`toHaveScreenshot()`）

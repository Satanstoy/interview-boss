# 前端路由改造设计文档

**日期：** 2026-06-15
**状态：** 已批准
**范围：** 引入 Vue Router，实现深度链接，重构 App.vue

---

## 1. 背景与问题

### 当前实现
- 页面切换通过 `App.vue` 中的 `activeTab` ref + `v-if` 条件渲染
- URL 通过 `history.pushState` + hash 同步 tab 名（如 `#MasterBank`）
- 没有使用 Vue Router，`router/index.js` 导出 null
- App.vue 承担所有编排（布局、认证、导航、页面渲染），约 950+ 行
- 布局组件 `DefaultLayout.vue` 和 `BlankLayout.vue` 存在但未使用

### 存在的问题
1. **无深度链接**：具体数据（题目、对话、JD）没有唯一 URL，无法收藏/分享/刷新恢复
2. **App.vue 膨胀**：8 个页面的渲染逻辑全在一个文件，违反单一职责
3. **浏览器历史粒度粗**：前进/后退只在 tab 级别，无法在列表→详情之间导航
4. **设置页是 overlay**：无法通过 URL 直接访问设置

---

## 2. 目标

1. 每个页面和具体数据项都有唯一 URL（深度链接）
2. App.vue 瘦身到 ~30 行
3. 浏览器前进/后退支持列表→详情级别的导航
4. 设置页变为独立路由
5. 渐进式迁移，每步可独立部署验证

---

## 3. 路由结构

### 3.1 路由映射表

| 当前 Tab | 路由路径 | 组件 | 深度链接 |
|----------|---------|------|---------|
| MasterBank | `/master-bank` | MasterBankView | ✅ `/master-bank/:id` |
| Chat | `/chat` | ChatView | ✅ `/chat/:sessionId` |
| JD | `/jd` | JdView | ✅ `/jd/:id` |
| Interview | `/interview` | InterviewView | ✅ `/interview/:id` |
| MockInterview | `/mock-interview` | MockInterviewView | ✅ `/mock-interview/:sessionId` |
| KnowledgeGraph | `/knowledge-graph` | KnowledgeGraphView | 无 |
| Import | `/import` | ImportView | 无 |
| Coding | `/coding` | CodingView | ✅ `/coding/:id` |
| Settings | `/settings` | SettingsView | 无 |
| Login | `/login` | LoginView | 无 |

### 3.2 特殊路由

| 路径 | 行为 |
|------|------|
| `/` | 重定向到 `/master-bank` |
| `/*` | 重定向到 `/master-bank`（或 404 页面） |

### 3.3 嵌套路由结构

```
/layouts/AuthenticatedLayout.vue    ← 已登录用户布局（侧边栏 + 内容区）
├── /master-bank        (MasterBankView)
│   └── /master-bank/:id (QuestionDetail)
├── /chat               (ChatView)
│   └── /chat/:sessionId (ChatView, 自动加载该 session)
├── /jd                  (JdView)
│   └── /jd/:id          (JdDetail)
├── /interview           (InterviewView)
│   └── /interview/:id   (InterviewDetail)
├── /mock-interview      (MockInterviewView)
│   └── /mock-interview/:sessionId
├── /knowledge-graph     (KnowledgeGraphView)
├── /import              (ImportView)
├── /coding              (CodingView)
│   └── /coding/:id      (CodingDetail)
└── /settings            (SettingsView)

/layouts/BlankLayout.vue           ← 无侧边栏布局
└── /login               (LoginView)
```

---

## 4. 布局系统

### 4.1 组件层级

```
App.vue（~30 行）
└── <router-view />

AuthenticatedLayout.vue（改造自 DefaultLayout.vue）
├── AppSidebar（侧边栏）
├── SiteHeader（顶部栏）
├── <Transition>
│   └── <router-view />  ← 嵌套路由出口
└── SettingsPage overlay（如保留）

BlankLayout.vue（改造自 BlankLayout.vue）
└── <router-view />
```

### 4.2 App.vue 瘦身

迁移前后职责对比：

| 职责 | 迁移前（App.vue） | 迁移后 |
|------|-----------------|--------|
| 布局编排 | App.vue 直接写 | AuthenticatedLayout.vue |
| 登录态判断 | `v-if="!isLoggedIn"` | 路由守卫 `beforeEach` |
| 页面渲染（8 个 v-if） | App.vue 400+ 行 | 各自的路由组件 |
| 侧边栏管理 | App.vue 内联 | AuthenticatedLayout.vue |
| 设置页 overlay | `showSettings` ref | 独立路由 `/settings` |
| URL hash 同步 | 手动 pushState | Vue Router 自动 |

---

## 5. 认证路由守卫

```js
router.beforeEach((to, from) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.name === 'login' && authStore.isLoggedIn) {
    return { name: 'master-bank' }
  }
})
```

路由元信息配置：
```js
{
  path: '/master-bank',
  component: MasterBankView,
  meta: { requiresAuth: true }
}
```

---

## 6. 导航迁移

### 6.1 侧边栏（AppSidebar.vue）

**当前：** emit `update:active-tab` 通知 App.vue
**迁移后：** 使用 `<router-link>` 导航，高亮从 `route.path` 判断

```vue
<router-link
  v-for="tab in sidebarTabs"
  :key="tab.key"
  :to="tab.route"
  :class="{ active: isActive(tab.route) }"
>
```

sidebarTabs 数据结构：
```js
{ key: 'MasterBank', label: '高频题库', route: '/master-bank', count: ... }
```

### 6.2 移动端 TabBar（TabBar.vue）

同 AppSidebar，改用 `router.push()` 或 `<router-link>`。

### 6.3 页面内导航

列表 → 详情：
```vue
<router-link :to="`/master-bank/${question.id}`">{{ question.title }}</router-link>
```

详情 → 返回：
```vue
<router-link to="/master-bank">← 返回题库</router-link>
```

---

## 7. 新文件结构

```
frontend/src/
├── main.js                    ← 添加 Vue Router 注册
├── App.vue                    ← 瘦到 ~30 行
├── router/
│   └── index.js               ← 路由配置
├── layouts/
│   ├── AuthenticatedLayout.vue ← 改造 DefaultLayout
│   └── BlankLayout.vue         ← 改造 BlankLayout
├── views/                     ← 🆕 页面级组件
│   ├── MasterBankView.vue
│   ├── QuestionDetail.vue     ← 🆕
│   ├── ChatView.vue
│   ├── JdView.vue
│   ├── JdDetail.vue           ← 🆕
│   ├── InterviewView.vue
│   ├── InterviewDetail.vue    ← 🆕
│   ├── MockInterviewView.vue
│   ├── KnowledgeGraphView.vue
│   ├── ImportView.vue
│   ├── CodingView.vue
│   ├── CodingDetail.vue       ← 🆕
│   ├── SettingsView.vue
│   └── LoginView.vue
├── components/
│   ├── AppSidebar.vue         ← 改用 router-link
│   ├── common/TabBar.vue      ← 改用 router-link
│   └── ... (其他不变)
```

---

## 8. 迁移策略

分 4 步渐进式迁移，每步可独立部署验证：

### Step 1：安装 Vue Router + 路由表 + 布局 + 守卫
- `npm install vue-router@4`
- 创建 `router/index.js` 路由配置
- 改造 `DefaultLayout.vue` → `AuthenticatedLayout.vue`
- 改造 `BlankLayout.vue`
- `main.js` 注册 router
- App.vue 改为只渲染 `<router-view>`
- **验证：** 所有 tab 通过 URL 访问，登录守卫生效

### Step 2：迁移页面内容到 views/
- 把 App.vue 中 8 个 tab 的 v-if 内容提取到对应 views/ 文件
- 每个 view 保持原有功能不变
- **验证：** 每个路由页面内容与迁移前完全一致

### Step 3：改造导航组件
- AppSidebar 改用 router-link，高亮从 route.path 判断
- TabBar 同理
- 移除 App.vue 中的 activeTab、pushState、popstate 相关代码
- **验证：** 导航功能不变，高亮正常，浏览器前进/后退正常

### Step 4：实现深度链接
- 添加 :id 子路由和对应详情组件
- 列表页添加 router-link 到详情
- 详情页添加返回链接
- **验证：** URL 可直接访问具体数据，刷新恢复，浏览器前进/后退正常

---

## 9. 依赖变更

| 操作 | 说明 |
|------|------|
| `npm install vue-router@4` | 唯一新增依赖 |

---

## 10. 不变的部分

- 所有业务组件内部逻辑不变（MasterBankList、ChatView 等）
- API 调用层不变
- 状态管理不变（composables）
- 后端不受影响
- 测试策略不变（现有测试可能需要适配路由）

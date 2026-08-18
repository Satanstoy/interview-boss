# Views — 页面视图

Vue Router 页面组件。View 只负责页面编排，业务能力由 `components/business/`、`components/common/` 和 `inject('appData')` 提供。

## 当前页面

| 文件 | 职责 |
|------|------|
| `MasterBankView.vue` | 高频题库页 |
| `ChatView.vue` | 模拟面试聊天页 |
| `JdView.vue` | JD 库页 |
| `InterviewView.vue` | 面经库页 |
| `PracticeView.vue` | 刷题页：消费应用壳共享题单状态，在认证应用壳内承载 Chat 风格闪卡刷题工作台 |
| `PracticeDecksView.vue` | 题单管理页：消费应用壳共享题单状态，管理“全部题/我的收藏”和用户自定义题单及题目关联 |
| `InsightsView.vue` | 洞察工作台编排：总览、岗位准备度、面试复盘三个路由共用数据快照；总览路由额外加载练习足迹图表数据 |
| `KnowledgeGraphView.vue` | 知识图谱页 |
| `ImportView.vue` | 导入工作台页 |
| `CodingView.vue` | 手撕代码页；页面外层与 `/chat` 的 `ChatView.vue` 保持一致的全屏高度和主工作区约束 |
| `SettingsView.vue` | 设置页：在主工作区外壳内承载 `SettingsPage.vue` |
| `ResumeView.vue` | 简历保存与优化页（删除有 ConfirmDialog 确认、删除按钮带 aria-label、optimize SSE 离开页面即 abort、岗位选择用 shadcn Select/Checkbox） |
| `LoginView.vue` | 登录页 |
| `NotFoundView.vue` | 404 页面：页面不存在提示 + 返回首页按钮 |

## 核心规则

- 页面组件命名：`<Domain>View.vue`（如 `ChatView.vue`、`SettingsView.vue`）
- View 组件负责页面编排（组合 business 组件），不直接调用 API
- API 调用通过 `services/` + `composables/` 封装；View 本身保持编排层，业务组件可通过 services/API 兼容层完成局部动作
- 已登录页面通过 `inject('appData')` 获取 `AuthenticatedLayout.vue` 提供的共享状态和操作
- 使用 `<script setup>` 语法
- 路径导入使用 `@/` 绝对路径

## 修改后必做

1. 新增 view 后更新根目录 CLAUDE.md 和 `frontend/CLAUDE.md`

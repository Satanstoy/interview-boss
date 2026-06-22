# Views — 页面视图

Vue Router 页面组件。View 只负责页面编排，业务能力由 `components/business/`、`components/common/` 和 `inject('appData')` 提供。

## 当前页面

| 文件 | 职责 |
|------|------|
| `MasterBankView.vue` | 高频题库页 |
| `ChatView.vue` | 模拟面试聊天页 |
| `JdView.vue` | JD 库页 |
| `InterviewView.vue` | 面经库页 |
| `MockInterviewView.vue` | 题目抽测页（紧凑 padding `px-4 py-4`） |
| `KnowledgeGraphView.vue` | 知识图谱页 |
| `ImportView.vue` | 导入工作台页 |
| `CodingView.vue` | 手撕代码页 |
| `SettingsView.vue` | 设置页：在主工作区外壳内承载 `SettingsPage.vue` |
| `LoginView.vue` | 登录页 |

## 核心规则

- 页面组件命名：`<Domain>View.vue`（如 `PracticeView.vue`、`AnalyticsView.vue`）
- View 组件负责页面编排（组合 business 组件），不直接调用 API
- API 调用通过 `services/` + `composables/` 封装
- 已登录页面通过 `inject('appData')` 获取 `AuthenticatedLayout.vue` 提供的共享状态和操作
- 使用 `<script setup>` 语法
- 路径导入使用 `@/` 绝对路径

## 修改后必做

1. 新增 view 后更新根目录 CLAUDE.md 和 `frontend/CLAUDE.md`

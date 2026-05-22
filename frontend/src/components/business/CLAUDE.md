# Business Components — 业务组件

与业务强耦合的 Vue 组件，按功能领域组织。

## 组件清单

| 组件 | 职责 |
|------|------|
| `AdminReview.vue` | 管理员审核面板 |
| `AnalyticsSidebar.vue` | 数据分析侧边栏 |
| `ChatMessage.vue` | Chat 消息气泡（Markdown 渲染） |
| `ChatView.vue` | Chat 主视图（SSE 流式） |
| `KnowledgeGraph.vue` | 知识图谱可视化 |
| `LoginModal.vue` | 登录弹窗 |
| `LoginPage.vue` | 登录页面（全屏） |
| `MasterBankList.vue` | 题库列表 |
| `MockInterview.vue` | 模拟面试 |
| `NewChatModal.vue` | 新建对话弹窗 |
| `PracticeMode.vue` | 练习模式选择 |
| `PracticePanel.vue` | 练习面板 |
| `ProfilePanel.vue` | 个人信息面板（简历上传） |
| `QuestionCard.vue` | 题目卡片 |
| `SearchFilterBar.vue` | 搜索过滤栏 |
| `SettingsPanel.vue` | 系统设置面板（管理员） |
| `StagingPanel.vue` | 暂存面板 |
| `UserMenu.vue` | 用户菜单 |

## 核心规则

- 业务组件可以依赖 `common/` 组件，但 `common/` 不能依赖 `business/`
- API 调用通过 `services/` 层，禁止在组件中直接 fetch
- 状态提升到 `App.vue` 或 composables，组件内不要维护全局状态

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件（如新增组件或改变职责）

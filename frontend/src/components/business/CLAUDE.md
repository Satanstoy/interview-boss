# Business Components — 业务组件

与业务强耦合的 Vue 组件，按功能领域组织。

## 组件清单

| 组件 | 职责 |
|------|------|
| `AdminReview.vue` | 管理员审核面板 |
| `AnalyticsSidebar.vue` | 数据分析侧边栏（分类目录、热门技术栈） |
| `CodeEditor.vue` | Monaco 代码编辑器封装（Python/C/Java） |
| `CodingPractice.vue` | 手撕代码练习主页面（题目列表 + 编辑器 + AI 评审）；内部侧栏折叠/展开动画对齐 ChatView |
| `ChatMessage.vue` | Chat 消息气泡（Markdown 渲染） |
| `ChatView.vue` | Chat 主视图（SSE 流式） |
| `ThinkingBlock.vue` | AI 思维链展示组件（可展开/折叠） |
| `InsightBlock.vue` | 面试官思考过程展示组件（可折叠卡片，显示 insight 列表） |
| `ExamDistribution.vue` | 考点分布图表（ECharts 饼图） |
| `KnowledgeGraph.vue` | 知识图谱可视化 |
| `LoginModal.vue` | 登录弹窗（密码登录、邮箱验证码、忘记密码重置、老用户绑定邮箱） |
| `LoginPage.vue` | 登录页面（全屏） |
| `MasterBankList.vue` | 题库列表 |
| `MockInterview.vue` | 模拟面试（配置面板 + 抽测模式）；布局紧凑化（header padding `px-4 py-3`，内容 padding `p-4`） |
| `NewChatModal.vue` | 新建对话弹窗 |
| `PracticeMode.vue` | 练习模式选择 |
| `PracticePanel.vue` | 练习面板 |
| `QuestionCard.vue` | 题目卡片 |
| `SearchFilterBar.vue` | 搜索过滤栏 |
| `SettingsPage.vue` | 统一设置页面（左侧工作区导航 + 右侧内容面板；个人信息、面试偏好、AI 配置、账户安全、管理员设置）；侧栏折叠/展开动画对齐 ChatView |
| `SettingsNav.vue` | 设置页左侧导航栏，风格对齐模拟面试/手撕代码的内部侧栏 |
| `SettingsProfile.vue` | 设置 - 个人信息（邮箱、简历、进度、题库模式、外观） |
| `SettingsInterview.vue` | 设置 - 面试偏好（岗位、收藏夹、AI 分类） |
| `SettingsAIConfig.vue` | 设置 - AI 配置（API Key、模型参数） |
| `SettingsSecurity.vue` | 设置 - 账户安全（当前密码/邮箱验证码两种改密方式、退出登录） |
| `SettingsAdmin.vue` | 设置 - 管理员设置（招聘季、分类管理、题库操作） |
| `StagingPanel.vue` | 暂存面板 |
| `UserMenu.vue` | 用户菜单 |

## 核心规则

- 业务组件可以依赖 `common/` 组件，但 `common/` 不能依赖 `business/`
- API 调用通过 `services/` 层，禁止在组件中直接 fetch
- 状态提升到 `App.vue` 或 composables，组件内不要维护全局状态
- 业务 UI 贴近 shadcn-vue workspace：卡片使用细边框/低阴影，聊天页使用 AI copilot 信息架构，用户入口固定在左侧应用壳底部。
- `LoginPage.vue` 是无 header 的全屏登录壳，品牌 logo + InterviewBoss 名称固定在左上角；中间登录卡片使用简短文案：标题“欢迎回来”、入口“免登录体验”，不要副标题标语、功能标签、营销卖点或复杂 dashboard preview。必须视口高度自适应（如 `h-dvh`/`h-full min-h-0`），不要使用 `calc(100vh-56px)`。

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件（如新增组件或改变职责）

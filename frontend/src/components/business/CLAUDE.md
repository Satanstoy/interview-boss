# Business Components — 业务组件

与业务强耦合的 Vue 组件，按功能领域组织。

## 组件清单

| 组件 | 职责 |
|------|------|
| `AdminReview.vue` | 管理员审核面板 |
| `AnalyticsSidebar.vue` | 数据分析侧边栏（分类目录、热门技术栈） |
| `CodeEditor.vue` | 轻量 LeetCode 风格代码编辑器封装（原生 textarea + 行号栏，避免 Monaco 的运行时开销） |
| `CodingPractice.vue` | 手撕代码练习主页面（ChatView 式全屏工作台 + 可收起题目侧栏 + LeetCode 式题目列表/描述/编辑器分栏 + AI 评审）；题单选择器位于全局 `SiteHeader`，保留收藏、题单和 Prompt + Markdown 导入 |
| `ChatMessage.vue` | Chat 消息气泡（Markdown 渲染）；从历史 metadata 恢复 reasoning_trace、tool_calls_trace、skill_trace、thinking、step、tool_steps、skill_name 和本轮采用题；`reasoning_trace.source === "model_reasoning"` 时优先展示 `thinking` chunks |
| `ChatView.vue` | Chat 主视图（SSE 流式）；新建面试支持 difficulty 和面经节奏来源，流式期间保留 step/tool_step/thinking，并在完成时合并后端 done.metadata；`chunk` 事件带 `replace=true` 时覆盖当前流式文本，用于后端完成后修正；regenerate 通过 assistant revision 重新加载消息，不删除或重复插入 user turn |
| `ReasoningTimeline.vue` | 面试官推理展示组件（可展开/折叠）；过滤 loading/context 等基础设施 step，把推理步骤、技能加载、工具调用串成左侧连线 timeline，连线需穿过圆点中心；展示 MiMo/DeepSeek reasoning_content、公开摘要 fallback、工具耗时、白名单参数和结果预览 |
| `ThinkingBlock.vue` | 旧版 AI 思维链展示组件（可展开/折叠） |
| `InsightBlock.vue` | 面试官思考过程展示组件（可折叠卡片，显示 insight 列表） |
| `ExamDistribution.vue` | 考点分布图表（ECharts 饼图） |
| `KnowledgeGraph.vue` | 知识图谱可视化 |
| `InsightsOverview.vue` | 洞察总览：证据状态、统计卡片和下一步行动 |
| `InsightsReadiness.vue` | 岗位准备度能力矩阵；承载旧知识图谱的辅助视图 |
| `InsightsReviews.vue` | 面试复盘会话列表和无数据入口 |
| `LoginModal.vue` | 登录弹窗（密码登录、邮箱验证码、忘记密码重置、老用户绑定邮箱） |
| `LoginPage.vue` | 登录页面（全屏） |
| `MasterBankList.vue` | 题库列表 |
| `MockInterview.vue` | 模拟面试（配置面板 + 抽测模式）；布局紧凑化（header padding `px-4 py-3`，内容 padding `p-4`）；支持临时选择模型留空则走全局默认 |
| `ModelSelectField.vue` | 模型选择字段（表单场景）：可搜索下拉 + 允许手动输入；`SettingsAIConfig` 全局默认与 `MockInterview` 临时覆盖复用同一组件 |
| `ModelSelector.vue` | 工具栏场景的模型切换按钮（图标+下拉，`ChatView` 使用）；不依赖外部 v-model，自带 fetchAvailableModels |
| `NewChatModal.vue` | 新建对话弹窗（模式、JD/简历、面试难度、参考面经节奏） |
| `PracticeMode.vue` | `/practice` 路由内的 Chat 风格闪卡刷题工作台：题单选择器由全局 `SiteHeader` 提供，侧栏只展示当前题单的搜索和题目列表；支持单卡翻答案、收藏、加入题单、AI 答案生成/编辑、可选自测与练习记录，题卡内部独立滚动并按容器尺寸自适应字号 |
| `PracticeDeckManager.vue` | `/practice/decks` 题单管理工作台：展示“全部题/我的收藏”和用户自定义题单，支持自定义题单 CRUD、公开范围、推荐模板，以及题目关联管理 |
| `PracticePanel.vue` | 练习面板 |
| `QuestionCard.vue` | 题目卡片（私有题显示「私有」徽标 + 分享按钮） |
| `SearchFilterBar.vue` | 搜索过滤栏 |
| `SettingsPage.vue` | 统一设置页面（左侧工作区导航 + 右侧内容面板；个人信息、面试偏好、AI 配置、账户安全、管理员设置）；侧栏折叠/展开动画对齐 ChatView |
| `SettingsNav.vue` | 设置页左侧导航栏，风格对齐模拟面试/手撕代码的内部侧栏 |
| `SettingsProfile.vue` | 设置 - 个人信息（邮箱、简历、进度、分享默认值、外观） |
| `SettingsInterview.vue` | 设置 - 面试偏好（岗位、收藏夹、AI 分类） |
| `InterviewDistributionSettings.vue` | 五类模拟面试题型比例与主问题数；系统默认或用户自定义保存 |
| `SettingsAIConfig.vue` | 设置 - AI 配置（API Key、模型参数） |
| `SettingsSecurity.vue` | 设置 - 账户安全（当前密码/邮箱验证码两种改密方式、退出登录） |
| `SettingsAdmin.vue` | 设置 - 管理员设置（招聘季、分类管理、题库操作） |
| `StagingPanel.vue` | 暂存面板（导入时分享设置：分享到公共题库 / 仅自己可见，所有用户可见） |
| `UserMenu.vue` | 用户菜单 |

## 核心规则

- 业务组件可以依赖 `common/` 组件，但 `common/` 不能依赖 `business/`
- API 调用通过 `services/` 层或兼容层 `api/index.js`，禁止在组件中直接 `fetch`
- 状态提升到 `App.vue` 或 composables，组件内不要维护全局状态
- 业务 UI 贴近 shadcn-vue workspace：卡片使用细边框/低阴影，聊天页使用 AI copilot 信息架构，用户入口固定在左侧应用壳底部。
- `CodingPractice.vue` 与 `/chat` 的 `ChatView.vue` 对齐外层工作台，同时遵循 LeetCode 题目页的信息架构：题单选择器放在应用全局 `SiteHeader`，当前题单区域只展示搜索、AI 导入和题目列表，侧栏支持收起/展开，右侧固定展示题目描述与编辑器；不再使用子页面顶栏、独立题库侧栏或难度筛选区。
- `PracticeMode.vue` 的默认路径以背八股为主：全局顶栏选择题单，侧栏只负责搜索/浏览当前题单，单卡内容优先，答案评估与历史记录作为卡片内的次级操作，长答案在题卡内部滚动；高频题权重和熟练度由后端队列算法驱动。
- `LoginPage.vue` 是无 header 的全屏登录壳，品牌 logo + InterviewBoss 名称固定在左上角；中间登录卡片使用简短文案：标题“欢迎回来”、入口“免登录体验”，不要副标题标语、功能标签、营销卖点或复杂 dashboard preview。必须视口高度自适应（如 `h-dvh`/`h-full min-h-0`），不要使用 `calc(100vh-56px)`。

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件（如新增组件或改变职责）

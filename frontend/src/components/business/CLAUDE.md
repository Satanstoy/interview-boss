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
| `InsightsOverview.vue` | 洞察总览：证据状态、统计卡片、岗位重点知识四象限图（前置）、「我的练习足迹」图表区（热力图/连击/趋势/难度/雷达/最近刷题）与「本周最该做」行动清单（后置），数据来自 `/api/insights` + `/api/insights/practice-activity` |
| `InsightsReadiness.vue` | 岗位准备度能力矩阵；承载旧知识图谱的辅助视图 |
| `InsightsReviews.vue` | 面试复盘会话列表和无数据入口 |
| `PracticeHeatmap.vue` | 练习足迹 - GitHub 风格打卡热力图（CSS grid 自绘 90 天，5 档颜色 + AppTooltip） |
| `PracticeStreakCard.vue` | 练习足迹 - 连续打卡卡片（当前/最长连击 + 激励文案 + 去刷题 CTA） |
| `PracticeTrendChart.vue` | 练习足迹 - 近 30 天刷题趋势（ECharts 柱状次数 + 折线平均分双轴） |
| `PracticeDifficultyChart.vue` | 练习足迹 - 难度分布环形图（ECharts 饼图 + 正确率 tooltip） |
| `PracticeRadarChart.vue` | 练习足迹 - 主题熟练度雷达图（ECharts，SRS 熟练度 top8） |
| `PracticeRecentTimeline.vue` | 练习足迹 - 最近刷题时间线（答题/复习徽标 + 分数/评级 + 相对时间） |
| `PracticeQuadChart.vue` | 岗位重点知识四象限决策图（ECharts Scatter + graphic 象限背景）：X=熟练度 Y=岗位热度，象限=重点突破/优势/可保持/不急；数据来自 `readiness.items`，象限分类纯函数在 `utils/quadrant.js` |
| `LoginModal.vue` | 登录弹窗（密码登录、邮箱验证码、忘记密码重置、老用户绑定邮箱） |
| `LoginPage.vue` | 登录页面（全屏） |
| `MasterBankList.vue` | 题库列表 |
| `ModelSelectField.vue` | 模型选择字段（表单场景）：可搜索下拉 + 允许手动输入；`SettingsAIConfig` 全局默认使用 |
| `ModelSelector.vue` | 工具栏场景的模型切换按钮（图标+下拉，`ChatView` 使用）；不依赖外部 v-model，自带 fetchAvailableModels |
| `ModelGuardDialog.vue` | AI 模型预检守卫弹窗：模型未配置/未接通时由 `useModelGuard` 触发，引导用户到设置页 AI 配置区 |
| `NewChatModal.vue` | 新建对话弹窗（模式、JD/简历、面试难度、参考面经节奏） |
| `PracticeMode.vue` | `/practice` 路由内的 Chat 风格闪卡刷题工作台：题单选择器由全局 `SiteHeader` 提供，侧栏只展示当前题单的搜索和题目列表；支持单卡翻答案、收藏、加入题单、AI 答案生成/编辑（仅管理员）、普通用户「AI 定制我的背诵稿」（基于公共参考答案 + 岗位/简历个性化改写，可编辑保存）、可选自测与练习记录，题卡内部独立滚动并按容器尺寸自适应字号；背诵稿区含「参考来源」折叠（联网搜索证据，随生成响应返回展示） |
| `PracticeDeckManager.vue` | `/practice/decks` 题单管理工作台：展示“全部题/我的收藏”和用户自定义题单，支持自定义题单 CRUD（纯私有，无公开范围选项）、推荐模板，以及题目关联管理 |
| `PracticePanel.vue` | 练习面板 |
| `QuestionCard.vue` | 题目卡片（私有题显示「私有」徽标 + 分享按钮）；答案区仅展示公共参考答案（题解），生成/编辑/手动编写按钮仅管理员；普通用户无生成入口，个人答案（背诵稿）不在题库卡片展示；答案区含「参考来源」折叠（联网搜索证据，`answer_sources` 为空不渲染）；来源详情对 `internal://`（用户粘贴 App 内部分享链接的无链接面经）降级显示「内部面经」徽标，不渲染 [原文] 链接 |
| `SearchFilterBar.vue` | 搜索过滤栏 |
| `SettingsPage.vue` | 统一设置页面（左侧工作区导航 + 右侧内容面板；个人信息、面试偏好、AI 配置、账户安全、管理员设置）；侧栏折叠/展开动画对齐 ChatView；支持 `?section=ai` 直达配置区 |
| `SettingsNav.vue` | 设置页左侧导航栏，风格对齐模拟面试/手撕代码的内部侧栏 |
| `SettingsProfile.vue` | 设置 - 个人信息（邮箱、简历、进度、分享默认值、外观） |
| `SettingsInterview.vue` | 设置 - 面试偏好（岗位、收藏夹、AI 分类） |
| `InterviewDistributionSettings.vue` | 五类模拟面试题型比例与主问题数；系统默认或用户自定义保存 |
| `SettingsAIConfig.vue` | 设置 - AI 配置（API Key、模型参数；保存/清除后失效模型缓存；「测试连接」实时探测模型可用性） |
| `SettingsSecurity.vue` | 设置 - 账户安全（当前密码/邮箱验证码两种改密方式、退出登录） |
| `SettingsAdmin.vue` | 设置 - 管理员设置（招聘季、分类管理、题库操作；含「聚合质量」tab：子分段切换「审查清单」|「AI 助手」|「来源健康」；审查清单审批 split/dedupe/精炼代表题，来源健康展示/合并重复公共面经） |
| `SettingsQuality.vue` | 设置 - 聚合质量审查清单（待审批/已处理/已拒绝三态；LLM 建议题面展示；批准/拒绝/批量高置信；记录永久保留） |
| `SettingsSourceHealth.vue` | 设置 - 来源健康（同签名重复公共面经）：面经/JD 子分段、重复组列表（签名/计数/保留 id/成员 URL）、「合并」按钮（确认后调用 merge，软删可恢复） |
| `SettingsQualityAssistant.vue` | 设置 - 聚合质量 AI 助手（仅管理员）：自然语言筛选/批量处理清单；工具轨迹可折叠展示；写操作渲染「待确认操作」卡片（确认→`/confirm`→`{message:""}` 续接让 LLM 确认并提下一步）；session_id 存 localStorage |
| `StagingPanel.vue` | 暂存面板（导入工作台）：文本/截图/来源链接三路输入 + 类型/季节/分享设置；分享设置（公共审核队列/仅自己可见）对所有用户可选；头部展示后台 Job 实时进度列表（阶段文案 + 进度条，失败红字可关闭）；非图片文件忽略时 toast 提示；清空非空内容需确认 |
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

# Bug 详细分析报告

**发现日期:** 2026-05-07
**状态:** 已确认
**审计范围:** frontend/src/ 全部组件

---

## BUG-001: 搜索框缺少清除按钮
- **位置:** `frontend/src/components/SearchFilterBar.vue:7-12`
- **症状:** 用户输入搜索关键词后，必须手动全选删除才能清空搜索
- **根因:** input 元素没有清除按钮（×）实现
- **影响:** 搜索体验不流畅，特别是移动端用户
- **严重程度:** P2

## BUG-002: 搜索无 loading 状态
- **位置:** `frontend/src/components/SearchFilterBar.vue`
- **症状:** 用户输入搜索词后，无法知道系统是否正在搜索
- **根因:** 没有传递 loading 状态给 SearchFilterBar 组件
- **影响:** 用户可能重复输入或认为系统无响应
- **严重程度:** P2

## BUG-003: 难度筛选使用 select 下拉
- **位置:** `frontend/src/components/SearchFilterBar.vue:14-23`
- **症状:** 难度筛选需要点击下拉菜单再选择，操作步骤多
- **根因:** 使用 `<select>` 元素而非按钮组
- **影响:** 筛选操作效率低
- **严重程度:** P3

## BUG-004: 答案区域操作按钮默认隐藏
- **位置:** `frontend/src/components/QuestionCard.vue:89-95`
- **症状:** "编辑"和"重新生成"按钮默认 `opacity-0`，只有鼠标 hover 答案区域才显示
- **根因:** 使用 `opacity-0 group-hover:opacity-100` 实现，移动端无法 hover
- **影响:** 用户可能不知道可以编辑或重新生成答案
- **严重程度:** P2

## BUG-005: 收藏按钮点击区域偏小
- **位置:** `frontend/src/components/QuestionCard.vue:40-44`
- **症状:** 收藏星标按钮只有 20x20px 的 SVG，点击区域小
- **根因:** 按钮没有额外的 padding 扩大点击区域
- **影响:** 移动端用户容易误触
- **严重程度:** P2

## BUG-006: 频率数字缺乏说明
- **位置:** `frontend/src/components/QuestionCard.vue:14-17`
- **症状:** 显示"频率 3"但用户不知道含义
- **根因:** 没有 tooltip 或说明文字解释频率的计算方式
- **影响:** 用户困惑
- **严重程度:** P3

## BUG-007: 练习面板左右分栏在小屏幕拥挤
- **位置:** `frontend/src/components/PracticePanel.vue:28`
- **症状:** 左右各 50% 在平板或小笔记本上内容被压缩
- **根因:** `w-1/2` 固定宽度，没有响应式断点
- **影响:** 阅读和输入体验差
- **严重程度:** P2

## BUG-008: 评估结果区域高度限制
- **位置:** `frontend/src/components/PracticePanel.vue:181`
- **症状:** 评估结果 `max-height: 55%` 可能导致详细建议被截断
- **根因:** 固定最大高度，没有考虑内容长度
- **影响:** 用户需要滚动查看完整评估
- **严重程度:** P3

## BUG-009: 练习历史无分页
- **位置:** `frontend/src/components/PracticePanel.vue:107-143`
- **症状:** 所有练习记录一次性加载，如果练习很多会很长
- **根因:** 没有分页或虚拟滚动
- **影响:** 列表过长时性能和体验下降
- **严重程度:** P3

## BUG-010: "换一批"无确认提示
- **位置:** `frontend/src/components/MockInterview.vue:71`
- **症状:** 用户已输入答案后点击"换一批"，答案会丢失且无确认
- **根因:** 直接调用 `loadQuestions()`，没有检查是否有未保存的输入
- **影响:** 用户可能意外丢失已输入的答案
- **严重程度:** P2

## BUG-011: 题目数量输入无实时验证
- **位置:** `frontend/src/components/MockInterview.vue:43`
- **症状:** 用户可以手动输入超出范围的数字（如 100），提交时才报错
- **根因:** 使用 `v-model.number` 但没有实时 clamp
- **影响:** 用户输入无效值后才知道
- **严重程度:** P3

## BUG-012: 无骨架屏 loading
- **位置:** `frontend/src/App.vue` 及各列表组件
- **症状:** 首次加载时显示空白或 spinner，没有骨架屏
- **根因:** 没有实现 skeleton loading 组件
- **影响:** 首屏加载体验差
- **严重程度:** P2

## BUG-013: 页面切换未滚动到顶部
- **位置:** `frontend/src/App.vue` TabBar 切换逻辑
- **症状:** 切换 Tab 后页面停留在当前位置，用户需要手动滚动
- **根因:** Tab 切换时没有 `window.scrollTo(0, 0)`
- **影响:** 导航体验不连贯
- **严重程度:** P3

## BUG-014: toast 错误持续时间过长
- **位置:** `frontend/src/composables/useNotification.js:6`
- **症状:** 错误 toast 持续 8 秒，可能遮挡其他内容
- **根因:** `error` 方法设置了 `{ duration: 8000 }`
- **影响:** 用户体验不佳
- **严重程度:** P3

## BUG-015: 部分按钮缺少 aria-label
- **位置:** 多个组件的图标按钮
- **症状:** 屏幕阅读器无法正确朗读按钮用途
- **根因:** 图标按钮没有 `aria-label` 属性
- **影响:** 可访问性差
- **严重程度:** P2

## BUG-016: 虚拟滚动高度在移动端不适配
- **位置:** `frontend/src/components/MasterBankList.vue:91`
- **症状:** `height: calc(100vh - 280px)` 在移动端可能过高或过低
- **根因:** 使用固定计算值，没有考虑移动端导航栏高度
- **影响:** 移动端列表显示异常
- **严重程度:** P2

## BUG-017: 注册密码强度提示不明显
- **位置:** `frontend/src/components/LoginModal.vue:25-31`
- **症状:** 密码输入框只显示"至少 8 位"，没有实时强度提示
- **根因:** 没有密码强度指示器
- **影响:** 用户不知道密码是否符合要求
- **严重程度:** P3

## BUG-018: StagingPanel 图片上传 capture 属性
- **位置:** `frontend/src/components/StagingPanel.vue:33`
- **症状:** `<input type="file" capture="environment">` 会强制移动端打开摄像头
- **根因:** 使用了 `capture` 属性
- **影响:** 用户无法从相册选择图片
- **严重程度:** P2

## BUG-019: AnalyticsSidebar 移动端位置
- **位置:** `frontend/src/App.vue:98-110`
- **症状:** 侧边栏在移动端显示在主内容上方，需要滚动很久才能看到题目
- **根因:** `lg:col-span-1` 在小屏幕占满宽度
- **影响:** 移动端首页体验差
- **严重程度:** P2

## BUG-020: 分页器不记住用户偏好
- **位置:** `frontend/src/components/PaginationBar.vue:47-54`
- **症状:** 用户修改每页条数后，刷新页面会重置
- **根因:** 没有将 pageSize 存储到 localStorage
- **影响:** 用户每次都要重新设置
- **严重程度:** P3

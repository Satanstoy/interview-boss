# Spec: 双层答案模型改造 — LeetCode 题解模式 + 搜索模块分工

> 位置: `backend/app/routers/answers.py` + `frontend/src/components/business/QuestionCard.vue` + `PracticeMode.vue`  
> 类型: 产品/架构纠偏 spec  
> 日期: 2026-08-05  
> 状态: 待实施  
> 触发背景: 公共题库与个人题库逻辑混乱，核心是"答案"存在公共（`question_bank.ai_answer`）与个人（`user_question_view.user_answer`）两份并展示方式怪异；同时 per-user 联网搜索模块（`search_service.py`）已上线但利用不充分。

## 结论

答案应改为 **LeetCode 题解模式**，核心转变：

```
公共参考答案（ai_answer）= 题解 → 一道题唯一一份，所有用户看到同一份，只有管理员/后台流水线可写
个人答案（user_answer）   = 背诵稿笔记 → 个人练习产出物，不参与题库展示，只出现在练习流程
普通用户不生成答案         → 用户侧动作是「练习对照 + 定制背诵稿」，不再重复调 LLM 生成内容雷同的答案
```

搜索模块在两个环节各司其职：**题解生成时搜索 = 内容源**（系统配置兜底、来源落库展示）；**背诵稿定制时搜索 = 个性化增强**（用户自己的 key、结合岗位/简历）。

## 现状与问题

### 数据模型现状

| 字段 | 语义 | 写入口 |
|------|------|--------|
| `question_bank.ai_answer` | 全局参考答案 | 管理员单题生成、**任何人批量生成**、后台流水线 |
| `user_question_view.user_answer` | 用户个人答案（`UNIQUE(user_id, question_bank_id)`） | 普通用户单题生成、手动保存、复制参考 |

### 问题清单

1. **批量生成权限不一致（最严重）** — `answers.py:126` `batch_generate_answers` 无 `is_admin` 判断，`answers.py:172-178` 直接写全局 `question_bank.ai_answer`。普通用户批量生成会覆盖管理员维护的公共参考答案。
2. **双答案并排展示** — `QuestionCard.vue:155-186` 同时展示"个人答案"标签和参考答案；`QuestionCard.vue:428` 又"优先显示个人答案"。用户生成过个人答案后，公共参考答案被顶掉，共享价值归零。
3. **答案内容无个人化却重复生成** — `answer_enrichment.py:27` 的 prompt 只含题目 + 联网搜索，不含用户岗位/简历/项目背景。同一道题所有用户生成内容雷同，每人重复花 token 生成一遍。
4. **个人题库的题也写全局字段** — `submit_service.py:38` `background_generate_answer` 对个人导入的题同样写 `ai_answer`，"个人题答案"与"公共参考答案"混用一个字段。
5. **搜索利用不充分** — `search_sources` 在 `answers.py:113` 返回但前端从未展示（全仓库无消费点）；公共答案后台生成时用提交者搜索配置（`submit_service.py:28` 传 `user_id`），提交者未配置则无搜索，质量不可控。
6. **采纳是死快照** — `use_reference_answer`（`answers.py:18`）复制后与公共答案解耦，管理员后续优化题解用户看不到。

## 目标形态

| 概念 | 归属 | 展示位置 | 生成方式 |
|------|------|---------|---------|
| 题解（公共参考答案） | 公共，一道题一份 | 题库卡片答案区（唯一答案展示位） | 管理员手动生成 / 后台流水线自动生成 |
| 背诵稿（个人答案） | 个人，每人一份 | 仅练习流程（翻转卡对照后、练习历史） | 用户手动编辑 / 「AI 定制我的背诵稿」 |
| 练习记录 | 个人 | 练习历史列表 | 练习评分时自动产生 |

## 详细设计

### 1. 权限规则（后端）

- `ai_answer` 唯一写入口：管理员 + 后台流水线（`background_generate_answer`）。
- `POST /api/master-bank/generate-answer/{id}`（`answers.py:69`）：加 `is_admin` 校验，非管理员返回 403。
- `POST /api/master-bank/batch-generate-answers`（`answers.py:125`）：加 `is_admin` 校验，非管理员返回 403。
- 管理员生成逻辑保持现状（已有有效答案直接返回，`answers.py:86`），补充「强制刷新」能力（可选：请求体 `force: true` 时跳过已有答案判断），解决管理员无法刷新题解的问题。
- `POST /api/master-bank/use-reference-answer/{id}`（`answers.py:18`）：废弃，前端移除入口；后端保留实现以兼容旧数据操作（或标记 deprecated 日志）。

### 2. 背诵稿定制（新端点）

新端点 `POST /api/master-bank/generate-recitation/{id}`（普通用户 + 管理员均可调用，仅能对自己可见的题调用，复用 `_build_bank_where_clause` 权限过滤）：

- **输入**：`question_id`；可选 body `{ "force": false }`。
- **基座**：公共参考答案 `ai_answer`（存在则作为改写素材，不重新想答案）；不存在时 404（提示先由管理员生成题解）或回退到纯生成（推荐：404 引导，保证题解优先）。
- **个性化上下文**：当前用户岗位（`get_user_job_position`）、简历文本（`get_resume_text`，可选截断）、用户记忆中相关经历（暂不接，作为后续增强）。
- **搜索**：复用 `prepare_answer_prompt` 的搜索机制，但查询词针对个性化增量（目标岗位最新趋势、简历项目技术实践），不是再搜题目本身；未配置搜索则跳过，不影响主流程（现有 best-effort 语义）。
- **输出**：写 `user_question_view.user_answer`（`ON CONFLICT` upsert，复用 `answers.py:56` 模式），返回 `{ status, answer, search_sources }`。
- **Prompt 结构**：新 prompt 模板 `RECITATION_PROMPT`（放 `core/prompts.py`）：以题解为素材，结合用户背景改写为口述级背诵稿，保持面试答案格式（开口句、要点、收尾），禁止改变技术事实。

### 3. 搜索模块分工

| 环节 | 触发 | 搜索配置 | 目的 | 结果 |
|------|------|---------|------|------|
| 题解生成 | 管理员/流水线 | 管理员用户配置 → 系统环境变量 `SEARCH_PROVIDER/SEARCH_API_KEY` 兜底 | 保证技术事实准确 + 时效性 | 来源落库，题解附带「参考来源」链接 |
| 背诵稿定制 | 用户主动 | 用户自己的配置（`get_user_search_config`） | 岗位/简历相关个性化增量 | 来源随背诵稿返回展示 |

- **来源落库**：`question_bank` 新增 `answer_sources TEXT`（JSON 数组：`[{title, url, snippet}]`），管理员生成/流水线生成时写入；题目详情 API 返回，前端答案区渲染为「参考来源」折叠链接（同 LeetCode 题解引用，增强可信度）。
- **流水线生成兜底**：`background_generate_answer` 的搜索配置责任明确为「提交者配置 → 系统环境变量兜底」（`config.py:130` 已有 fallback，保持现状并补测试）；公共题库的题优先由管理员生成以确保质量。

### 4. 前端改造

**`QuestionCard.vue`（主战场）**
- 删除「个人答案」标签并排展示（`:155-156`）与"优先显示个人答案"逻辑（`:428-430`）。
- 答案区只渲染 `ai_answer`（题解）+「参考来源」链接（如有 `answer_sources`）。
- 生成/编辑按钮按角色：管理员保留「编辑」「生成」「批量生成」；普通用户移除「生成」「使用参考答案」按钮（`:151`、`:184-188`）。
- 普通用户新增「定制我的背诵稿」次要操作（本端点未实现前先隐藏，随 Phase 3 上线）。

**`PracticeMode.vue`（小改）**
- 形态不变（已是翻转卡：先口述 → 查看参考答案 → 打分 → 历史）。
- 移除普通用户的「生成」入口（`:348` `handleGenerate`），生成仅管理员。
- 翻转卡「查看参考答案」后新增「AI 定制我的背诵稿」按钮（调用新端点，写入后进入「我的背诵稿」编辑态），保留手动编辑 + 保存。
- 练习历史（`:137`）语义标注为「练习记录」，与背诵稿区分。

**`PracticePanel.vue`**
- 「编辑」按钮（`:83`）仅管理员保留；普通用户答案区只读展示题解。

### 5. 数据迁移

- `question_bank` 新增 `answer_sources TEXT DEFAULT NULL`（JSON 数组）。已有数据不回溯填充，来源为空则前端不渲染「参考来源」。
- `user_question_view.user_answer` 存量数据保留，前端不再于题库卡片展示（练习历史不受影响，历史数据在 `user_practice_history`，不同表）。

## 接口变更汇总

| 端点 | 变更 |
|------|------|
| `POST /api/master-bank/generate-answer/{id}` | 加管理员校验（403）；可选 `force` 刷新 |
| `POST /api/master-bank/batch-generate-answers` | 加管理员校验（403） |
| `POST /api/master-bank/generate-recitation/{id}` | **新增**：定制背诵稿 |
| `POST /api/master-bank/use-reference-answer/{id}` | 废弃（前端移除入口） |
| `PUT /api/master-bank/save-user-answer/{id}` | 保留，语义 = 保存背诵稿 |
| 题目详情/列表返回 `answer_sources` | 新增字段 |

## 实施顺序

- **Phase 1（权限修复，后端）**：`generate-answer` / `batch-generate-answers` 加管理员校验 + 测试；前端隐藏普通用户生成按钮。独立可上线，修复污染问题。
- **Phase 2（题解形态，前端）**：`QuestionCard.vue` 删双答案、改题解展示；`PracticeMode.vue` 移除普通用户生成入口。
- **Phase 3（背诵稿定制）**：新端点 + `RECITATION_PROMPT` + 简历/岗位上下文 + 搜索利用 + 前端「定制我的背诵稿」入口 + 测试。
- **Phase 4（来源落库与展示，可选）**：`answer_sources` 迁移 + 写入 + 前端展示 + 系统配置兜底测试。

## 不在范围内

- 不做「答案社区」（用户之间共享答案/点赞）。
- 不做背诵稿的复习调度（现有练习间隔复习已覆盖）。
- 不接记忆召回（`memory_recall_service`）到背诵稿上下文（后续增强项）。
- 不删除存量 `user_answer` 数据。

## 风险与对策

| 风险 | 对策 |
|------|------|
| 管理员手动维护题解成本上升 | 流水线自动生成保留（后台任务 + 批量生成仅管理员）；`force` 刷新兜底 |
| 普通用户失去"自己生成答案"能力感到突兀 | 背诵稿定制入口提供同等价值（更个性化）；题库页无题解时提示由管理员生成 |
| 背诵稿定制调用成本（LLM + 搜索）不可控 | 仅在用户显式点击时触发；复用公共题解作基座避免重复「从头生成」；来源展示提升感知价值 |
| 批量生成改造破坏现有管理员流程 | Phase 1 只加校验不动逻辑，管理员行为完全不变 |

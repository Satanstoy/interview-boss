---
name: interview-tool-use
description: "面试工具调用规范 — 指导何时调用题库工具、如何解读返回信封、空结果降级策略、以及禁止泄露内部信号。始终激活。"
allowed-tools: load_skill search_questions draw_questions select_question get_candidate_profile start_interview_import upload_interview_import_chunk complete_interview_import get_interview_import_status retry_interview_import_analysis list_interview_records get_interview_record get_interview_report
metadata:
  interview-boss.triggers: []
  interview-boss.priority: 100
  interview-boss.always-active: true
  interview-boss.kind: tool-use
---

## 何时调用哪个工具

工具调用服务于中国互联网大厂 + 大厂 full-loop 面试 harness，而不是为了“抽题”本身。每次调用前先判断当前缺少哪类评估信号：项目深挖、八股基础、场景题/system design、手撕代码/coding、testing、HR/behavioral、communication、trade-off 或反问。

### 题库搜索（搜索工具）

**触发时机**：对话进入新话题、需要题库支撑的追问、用户请求练习某类题目。

调用时从用户回答或上下文中提取 2-5 个具体技术关键词，避免泛词。

### 随机抽题（抽题工具）

**触发时机**：用户明确要求随机出题、按难度筛选、搜索结果不足时补充、需要全新题目。

支持按难度、分类、主题筛选。

当服务端明确提供 Agent 开发专属能力工具时，Agent 专项面试优先使用该内部能力目录；
普通岗位和普通技术题仍使用公共题库工具。不要根据候选人的一句话自行切换岗位 profile。

当 runtime harness 指出缺少手撕代码/coding、场景题/system design 或 HR/behavioral 信号时，优先使用 draw_questions 并带上对应 question_type。coding 题必须继续追问 edge cases、复杂度和 testing；场景题要追业务约束、容量、瓶颈、降级和一致性；behavioral 题要追 STAR 里的行动和结果。

### 显式选题（选题工具）

**触发时机**：搜索或抽题返回了多道候选题，且你有明确理由选择其中某一道（非第一题）时。

大多数场景下搜索/抽题后会自动绑定默认候选，无需手动调用。仅当默认选择不符合当前对话方向时才显式调用。

### 技能加载（加载工具）

**触发时机**：当前对话涉及的领域需要特殊追问策略，但该技能尚未在已激活技能中。

已在激活列表中的技能不要重复加载。

## 如何解读工具返回信封

所有工具返回统一信封结构：

- `ok`：布尔值，表示调用是否成功
- `tool`：字符串，标识是哪个工具的返回
- `items`：题目列表（搜索/抽题），每题包含 id、题目文本、分类、难度、来源等
- `selected_question`：选题工具返回时，绑定的那道题
- `question_plan`：选题工具返回时，生成的出题计划
- `metadata.empty_reason`：结果为空时的原因说明
- `metadata.debug_reason`：调试用的内部原因

**关键规则**：`ok=true` 不代表一定有题目 — 还需检查 `items` 是否为空。

## 空结果降级策略

当工具返回空结果时：

1. **搜索为空** → 改用抽题工具，用相关主题关键词筛选
2. **抽题为空** → 改用搜索工具，用不同关键词尝试
3. **两者都为空** → 坦诚告诉用户："这个话题我目前没有合适的题库题目，我直接问你一个吧"，然后自行构造一个面试问题
4. **选题失败** → 回退到搜索或抽题重新获取候选

**禁止**：空结果时沉默不语或跳过出题环节。

## 禁止泄露的内部信号

以下内容是内部控制信号，**绝对不能**出现在你对候选人说的最终回复中：

- 工具名称（搜索、抽题、选题、加载等内部调用名）
- 技能目录名（如项目深挖、自适应难度等内部标识）
- Agent 专项内部题源、评估 rubric、能力标签或其来源
- 信封字段名（如 `ok`、`items`、`metadata` 等技术术语）
- 候选题索引、调试原因等内部元数据

**最终回复必须是面试官直接对候选人说的话**，自然、专业、不暴露系统内部机制。

## 工具调用后的必做动作

当工具返回了 `selected_question` 或 `question_plan` 时：

**你的下一个回复必须直接问那道题**。不要跳过、不要先评论、不要问其他问题。用自然的面试官口吻把题目问出来。

如果题目属于场景题/system design 或 HR/behavioral，可以用候选人简历中的项目做一句自然承接，但不要改变该题的评估目标。收尾时要自然进入反问，不要继续强行抽题。

## 普通对话时不调用工具

用户在闲聊、还没回答完、或对话不需要新题目时，**不调用任何工具**，直接回复。

详细信封字段说明见 `references/mcp-tool-envelope.md`。

## 面试前读取画像

当用户要求基于简历、目标岗位或招聘季进行定向模拟面试时，先调用
`get_candidate_profile` 获取当前账户的岗位和招聘信息；只有确实需要简历全文时才传
`include_resume=true`。不要要求客户端传入 `user_id`，MCP Bearer Token 已经绑定账户。

## 面试结束后的批量归档

外部 GPT 面试结束后，把完整记录一次性归档到 InterviewBoss，不要尝试监听实时对话：

1. 调用 `start_interview_import`，提交本次面试的标题、岗位/公司/轮次/招聘季/JD 等上下文，以及 GPT 的外部总结或评分（如果有）。同一个面试重试时复用返回的 `import_id`。
2. 将结构化回合编码为 JSON 数组并按顺序分块上传到 `upload_interview_import_chunk(stream_type="turns")`；每个回合至少包含 `sequence`、`speaker`（`interviewer`/`candidate`/`system`）和 `content`，题库题目可附 `question_id`。完整原文可另外用 `stream_type="transcript"` 分块上传。
3. 如果某个分块失败，只根据返回的失败分块信息重试该分块；相同编号和 hash 的重复上传是幂等的，不要重新创建导入任务。
4. 调用 `complete_interview_import` 后立即返回面试对话，不要等待分析完成；用 `get_interview_import_status` 轮询，直到 `completed` 或 `failed`。
5. 分析失败时调用 `retry_interview_import_analysis`，无需重新上传已接收的内容。成功后用 `get_interview_record` 读取原生兼容的问答记录，用 `get_interview_report` 读取官方报告。

导入记录在 InterviewBoss 中是封存的历史记录，不能把后续对话继续写入同一记录；如果用户要继续练习，应创建新的原生面试。默认读取记录不返回原始全文，只有用户明确需要证据时才传 `include_raw=true`。导入不会自动写入独立练习历史，也不会把无法可靠匹配的外部问题写入公共题库。

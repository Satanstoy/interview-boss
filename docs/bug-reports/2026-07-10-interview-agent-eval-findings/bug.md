# 模拟面试 Agent 评测问题报告

**日期：** 2026-07-10
**类型：** Bug 分析 / 待修复
**状态：** 待修复
**来源：** `backend/scripts/eval_interview_agent.py` 生成的真实评测 JSON/Markdown

## 结论摘要

本次评测报告里有一部分是评估报告展示噪声，但也暴露了模拟面试 agent 的真实问题。

确认属于 agent 的问题有三类：

1. 工具调用和最终提问脱节：agent 多次调用 `search_questions` / `draw_questions`，但没有把候选题绑定为实际问题，导致题库工具成为无效背景操作。
2. 强绑定题目失败时会整轮报错：当已有 `must_ask` 计划但模型输出偏离时，repair / rewrite 全失败后直接抛错，候选人会看到空回复或 SSE error。
3. 收尾和反问阶段缺少稳定的后端控制：agent 可以自然进入反问和告别，但不稳定生成结构化总结；候选人反问时也容易只短句回应后立刻拉回主流程。

不应归因给 agent 的噪声：

1. Markdown 报告把 4/5、5/5 维度也显示为 FAIL，这是 `eval_interview_agent.py` 报告渲染 bug，不是 agent 在这些维度失败。
2. 短场景要求 full-loop 全覆盖会偏严，例如 6 轮 `tool_timing` 同时要求算法、系统设计、HR/软素质完整覆盖，不应直接等同于产品缺陷。

## 证据

### 1. 工具调用没有转化为实际题目

最新 `tool_timing` 评测：

- 文件：`backend/data/evaluations/eval_tool_timing_20260710_132144.json`
- 指标：`turn_count=6`、`tool_count=8`
- 结果：`selected_ids=[]`、`asked_questions=[]`
- 事件：有 6 次 `selected_question` 事件，但全部是 `question=null`

代表性事件：

```text
turn 3 selected_question = conversation:candidate_questions_not_explicitly_used:null
turn 4 selected_question = conversation:candidate_questions_not_explicitly_used:null
turn 5 selected_question = conversation:candidate_questions_not_explicitly_used:null
turn 6 selected_question = conversation:candidate_questions_not_explicitly_used:null
```

这说明 agent 确实检索了题库候选，但最终问题来源被记录为 conversation，而不是题库选题。面试文本本身质量并不差，问题在于工具链路没有形成可追踪、可去重、可覆盖统计的选题闭环。

相关代码路径：

- `backend/app/agents/chat/react_loop.py`：工具调用后只尝试 `_maybe_create_question_plan(state)`。
- `backend/app/agents/chat/question_plan.py`：`_maybe_create_question_plan()` 只有在 `_should_create_question_plan()` 返回 true 时才绑定题目。
- `backend/app/agents/chat/metadata.py`：如果没有绑定题目，会写入 `candidate_questions_not_explicitly_used`。

根因判断：

当前设计允许 `search_questions` 只是“参考候选题”。这在项目深挖场景可接受，但在 full-loop harness 明确缺少某个覆盖维度时，会造成工具调用被执行、候选题被展示给模型、但最终覆盖 ledger 和 DB 都没有记录题目。

### 2. 强绑定题目失败会导致空回复 / error

最新 `counter_question_flow` 评测：

- 文件：`backend/data/evaluations/eval_counter_question_flow_20260710_131046.json`
- 指标：`selected_ids=[6370, 6328, 6074]`、`asked_questions=[6370, 6328, 6074]`
- 错误：`Question plan enforcement failed: LLM rewrite unavailable; plan question_text='Agent范式在项目中有没有用过？'`
- 现象：第 7 轮 assistant 为空字符串，SSE 中出现 error。

代表性事件：

```text
turn 7 assistant = ""
steps = loading, context, understanding, draw_questions, search_questions, draw_questions, generating
error = 处理消息时出现错误: Question plan enforcement failed: LLM rewrite unavailable; plan question_text='Agent范式在项目中有没有用过？'
```

相关代码路径：

- `backend/app/agents/chat/answer.py`：`_enforce_question_plan_on_text()` 会先检查 plan adherence，再尝试 repair。
- repair 失败后调用 `_rewrite_transition_with_llm()`。
- rewrite 仍失败时直接抛 `GenerationError(code="question_plan_generation_failed")`。
- `backend/app/agents/chat/pipeline.py` 外层捕获异常后只发 SSE error。

根因判断：

当前问题不是“缺少一个机械 fallback”，而是自然出题链路不够可靠。强绑定题目是后端控制流承诺，但最终展示给用户的仍必须是自然的面试官提问。若系统只能通过硬编码转场句拼出题目，说明 plan enforcement / question writer 本身还没有达到产品要求。

### 3. 收尾总结和反问处理不稳定

最新 `natural_closing` 评测：

- 文件：`backend/data/evaluations/eval_natural_closing_20260710_131717.json`
- 指标：`turn_count=14`、`tool_count=12`
- 结果：`selected_ids=[]`、`asked_questions=[]`、`has_summary=false`
- 现象：第 10 轮进入“你有什么想问我们的吗？”，第 11 轮回答候选人反问并说“面试到此结束”，第 12-14 轮只做简短告别，没有结构化总结。

代表性回复：

```text
turn 10: 技术面到这里整体覆盖得差不多了。你有什么想问我们的吗？
turn 11: ... 今天技术面整体到这里。你对RAG系统从检索到缓存到一致性的完整链路讲得比较清楚...
turn 12: 好，再见。祝后续顺利。
turn 13: 好，面试到这里。再见。
turn 14: 再见，祝你一切顺利。
```

相关代码路径：

- `backend/app/agents/chat/stop_policy.py`：自然停止依赖 coverage 和 message count。
- `backend/app/agents/chat/decision_config.py`：默认 `soft_close_message_count=32`，`hard_stop_message_count=56`。
- `backend/app/agents/chat/prompts.py`：提示词里要求候选人反问后系统自动生成结构化总结，但实际流程没有稳定兑现。
- `backend/app/agents/chat/summary.py`：已有结构化总结能力，但本场景没有稳定进入 summary workflow。

根因判断：

收尾仍有一部分落在 ReAct 自然生成里，而不是完全由后端 `closing_stage` / stop policy 控制。短评测场景里，候选人已经进入反问和告别，agent 却没有可靠切到结构化总结，导致评测看到 `has_summary=false`。

### 4. 非 agent 问题：报告展示把所有维度标成 FAIL

多份 Markdown 报告里出现 4/5、5/5 仍显示 `FAIL` 的情况。根因在评估脚本报告生成逻辑，不是 agent 表现。

相关代码路径：

- `backend/scripts/eval_interview_agent.py` 的 LLM 评分分支只写入 `score`、`reasoning`，没有写 `passed`。
- 同文件报告生成分支用 `item.get("passed")` 渲染 PASS/FAIL。
- 因为缺失字段被当作 false，导致所有 LLM 评分维度都显示 FAIL。

修复方向应放在 eval 拆分完成后处理：LLM judge item 应补 `passed = score >= 3`，或报告渲染用 `score` 推导状态。

## 影响

### 产品影响

- 用户看到的面试问题可能仍然自然、深入，但题库工具带来的可控性、去重、覆盖度统计没有稳定生效。
- 一旦强绑定题目生成失败，用户会遇到空回复或错误，属于体验硬伤。
- 收尾阶段可能只有礼貌告别，没有结构化复盘，降低模拟面试的闭环价值。

### 工程影响

- `interview_asked_questions` 记录缺失会影响跨轮、跨会话去重。
- coverage ledger 无法可靠知道某个维度是否由题库题完成。
- eval 报告的假 FAIL 会干扰后续判断，容易把已表现良好的 depth / flow / role adherence 当作失败项。

## 建议修复顺序

### P0：强绑定题目必须自然生成，不能空回复也不能机械兜底

修复目标：

- `must_ask` plan 已存在时，后端必须把本轮导入一个专门的 natural question writer / repair workflow，而不是让通用 ReAct 自由发挥后再补救。
- repair 失败时允许内部重试、换更窄的 prompt、降低温度、扩大上下文或切换到专门的出题模型，但不能向用户展示硬编码模板式转场。
- 输出必须同时满足两件事：语气自然、问题目标仍围绕 `plan.question_text`。
- 如果多次自然生成都失败，应记录为内部 generation failure，并进入可观测告警；不应把机械拼接文本伪装成正常面试官回复。
- metadata 标记 `repair_attempted=true`、`natural_rewrite_attempts=N`、`question_plan_adherence`，方便评测识别自然生成链路是否稳定。

建议测试：

- 构造 `next_question_plan.must_ask=true`，mock 首次 ReAct 输出偏离，断言进入 natural question writer，并输出自然提问。
- 构造自然提问包含计划题意但不是题库原文，断言 adherence 通过。
- 构造多次 rewrite 失败，断言不会输出硬编码转场文本，并记录可观测 error / failure metadata。

### P1：coverage-driven 题库绑定

修复目标：

- 当 full-loop harness 判定缺少 `algorithm_coding`、`system_design`、`behavioral` 等覆盖维度时，工具调用后必须绑定题目或明确记录 retrieval miss。
- `search_questions` 返回低相关结果时，应 fallback 到 `draw_questions(question_type=...)`，而不是继续让模型自由追问。
- `select_question` 不应只依赖模型主动调用；后端可以在强覆盖缺口下自动绑定最高可用候选。

建议测试：

- 构造缺少算法维度且工具返回算法候选，断言 `selected_question`、`question_plan`、`interview_asked_questions` 都有记录。
- 构造 search 结果全部弱相关，断言走 draw fallback 或记录 `retrieval_miss`，不会产生 `candidate_questions_not_explicitly_used` 的假成功。

### P2：收尾 workflow 拆成自然收尾语 + LLM 结构化总结

修复目标：

- 候选人已经完成反问并表达结束时，后端应根据 `closing_stage` 进入 closing workflow。
- closing workflow 分两步：
  1. 由面试官 LLM 输出一段自然收尾语，例如感谢、结束语、后续说明，保持真实面试语气。
  2. 随后调用独立的 LLM 级结构化总结组件，根据完整面试记录生成面试总结。
- 不依赖 ReAct 自己说“面试结束”来代表完成；总结生成应是后端显式步骤。
- 结构化总结至少包含整体表现、技术主题、亮点、不足/待观察、后续建议。
- 总结输出应有稳定 schema，再渲染成 Markdown，避免自由文本漏字段。

建议测试：

- 构造 `closing_stage=candidate_question_asked` 且用户反问已回答后的下一轮，断言先输出自然收尾语，再调用结构化总结。
- 构造候选人连续告别，断言不会只输出短告别，至少第一次收尾生成结构化总结。
- 构造 summary LLM 返回缺字段，断言 schema 校验失败后重试或降级为结构化模板，但不能只给一句“再见”。

### P3：eval 报告展示修复

修复目标：

- LLM judge 的 `items` 补 `passed` 字段，或报告生成时用 `score >= 3` 推导 PASS。
- 报告里区分“总场景通过”和“单维度低分”，避免全部标成 FAIL。

## 不建议的修复方式

- 不建议把每一次 `search_questions` 都强制绑定第一题。项目深挖场景中，工具结果可能确实不如自然追问合适。
- 不建议用硬编码转场句作为用户可见 fallback。面试官不能自然提问本身就是需要修复的问题，机械兜底会掩盖质量缺陷。
- 不建议只改 prompt 要求“请使用工具结果”。当前问题发生在状态机和 metadata/ledger 记录边界，必须有后端控制流约束和自然提问生成校验。
- 不建议用评估脚本的 Markdown FAIL 直接指导修 agent；应优先看 JSON 的 `score`、`reasoning`、`metrics` 和原始事件。

## 后续派发建议

等 `eval_interview_agent.py` 拆分完成后，建议按以下顺序派发：

1. 先修 `answer.py` / question writer 的自然 plan enforcement，防止用户可见 error 和机械兜底。
2. 再修 `question_plan.py` / `react_loop.py` 的 coverage-driven binding。
3. 再修 `stop_policy.py` / `turn_controller.py` / `summary.py` 的两阶段收尾状态机：自然收尾语 + LLM 结构化总结。
4. 最后修 eval 报告渲染，避免分析噪声继续污染判断。

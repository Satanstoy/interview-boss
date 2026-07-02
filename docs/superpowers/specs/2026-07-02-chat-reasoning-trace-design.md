# Chat Reasoning Trace — DS 风格思考与工具调用详情

**日期**: 2026-07-02
**状态**: Draft
**范围**: 模拟面试 Chat 的 AI 思考摘要、工具调用、skill 加载展示与持久化

## 背景

现有 Chat 已有 `ReasoningTimeline.vue`，后端也会把 `steps`、`tool_steps`、`thinking` 合并到 assistant message metadata。但真实使用中仍有几个缺口：

1. 多数 ReAct 回合没有模型 `reasoning_content`，`thinking=[]`、`thinking_duration=0`，用户看不到“思考了多久”。
2. `force_search_guard` 分支会执行 `search_questions` / `draw_questions`，但没有记录 `tool_step`，导致强制检索路径缺少工具调用详情。
3. 前端第一层展示偏工程化，用户需要先看到“分析回答 / 检索题库 / 加载策略 / 组织追问”这类直觉动作，点击后再看工具名、参数、耗时、结果等调试细节。
4. E2E mock、后端测试和用户真实使用必须落到同一份 metadata，刷新历史消息时不能丢 trace。

本设计是对 `2026-06-16-reasoning-timeline-design.md` 和 `2026-07-01-interview-state-rhythm-observability-design.md` 的增量收敛，不替换既有 `steps` / `tool_steps` / `thinking`，而是定义新的稳定展示契约。

## 目标

1. 做出类似 DeepSeek 的折叠思考面板：`已思考 4.2 秒 · 调用 2 个工具 · 加载 1 个策略`。
2. 工具调用必须可点击展开，展示用户能理解的详情：用途、参数摘要、耗时、结果数、候选题、采用题、fallback / error 原因。
3. skill 加载必须可见，展示中文策略名和加载原因，但不泄露完整 skill prompt。
4. 后端所有执行路径统一留下 trace：普通 ReAct、force search guard、end interview、E2E/mock、真实用户请求。
5. 新消息流式显示和历史消息刷新显示使用同一份 metadata。

## 非目标与安全边界

- 不展示隐藏原始 CoT。前端展示的是模型显式返回的 reasoning content 或后端生成的公开思考摘要。
- 不展示 raw tool args、完整工具输出、完整 skill instruction、API key、简历全文、JD 全文。
- 不把 trace 数据作为面试逻辑事实来源；事实来源仍是 `ChatState`、`InterviewLedger`、message metadata 中的题目/阶段字段。

## 用户体验设计

### 折叠标题

完成后标题：

```text
已思考 4.2 秒 · 调用 2 个工具 · 加载 1 个策略
```

流式中标题：

```text
思考中 3 秒 · 正在检索题库
```

如果没有工具或 skill，只省略对应片段：

```text
已思考 1.8 秒 · 4 步
```

### 面板内容

面板分三段，默认折叠，用户点击打开：

1. **思考过程**
   - 优先展示模型显式返回的 `reasoning_content` / Anthropic thinking block。
   - 如果模型没有返回 reasoning，则展示后端生成的公开摘要，例如：
     - `分析候选人回答是否覆盖项目职责`
     - `判断需要继续项目深挖`
     - `准备检索题库中的相关高频题`
   - UI 文案使用“思考摘要”，避免暗示这是完整隐藏推理。

2. **执行步骤**
   - 展示用户直觉动作，不直接暴露工程名：
     - `加载上下文`
     - `分析回答`
     - `加载项目深挖策略`
     - `检索题库`
     - `采用面试题`
     - `组织追问`
   - 点击每个步骤可见 `reason` / `insight`。

3. **工具调用**
   - 每个工具一行：
     ```text
     检索题库 · 318ms · 3 结果
     ```
   - 点击展开：
     ```text
     工具: search_questions
     参数: keywords=Redis, 缓存; question_type=knowledge_probe
     耗时: 318ms
     结果: 3
     采用题: Redis 缓存穿透和布隆过滤器的关系
     降级: 未触发
     ```
   - 失败或空结果时展示：
     ```text
     检索题库 · 42ms · 0 结果 · 已降级
     empty_reason: no_query
     debug_reason: validation_failed
     ```

### 工程名和用户文案映射

| 内部字段 | 用户第一层文案 | 展开细节 |
| --- | --- | --- |
| `loading` | 加载上下文 | 最近消息、记忆、session notes |
| `context` | 读取个人画像 | 简历 / JD / 岗位上下文是否可用 |
| `understanding` | 分析回答 | 意图、关键词、是否需要题库 |
| `load_skill` | 加载策略 | skill 中文名、skill_name、加载原因 |
| `search_questions` | 检索题库 | 参数摘要、耗时、结果数、候选题 |
| `draw_questions` | 抽取题目 | 参数摘要、耗时、结果数、候选题 |
| `select_question` | 采用面试题 | candidate_index / question_id / 采用原因 |
| `force_search_guard` | 补充检索题库 | 触发原因、后续工具调用 |
| `generating` | 组织追问 | 基于上下文和候选题生成回复 |
| `closing` | 生成总结 | 收尾原因和总结状态 |

## 后端数据模型

保持旧字段兼容，同时新增更适合前端展示的稳定字段：

```json
{
  "reasoning_trace": {
    "version": 1,
    "duration_ms": 4200,
    "source": "model_reasoning|summary_fallback|timing_only",
    "summary": [
      "分析候选人回答是否覆盖项目职责",
      "判断需要加载项目深挖策略",
      "准备检索题库中的相关高频题"
    ],
    "model_reasoning": [
      {
        "chunks": ["模型显式返回的 reasoning 片段"],
        "duration_ms": 1200,
        "truncated": false
      }
    ]
  },
  "tool_calls_trace": [
    {
      "tool_name": "search_questions",
      "label": "检索题库",
      "message": "正在检索相关面试题...",
      "args_summary": {
        "keywords": ["Redis", "缓存"],
        "question_type": "knowledge_probe"
      },
      "elapsed_ms": 318,
      "ok": true,
      "result_count": 3,
      "result_ids": [101, 102, 103],
      "result_preview": [
        {
          "id": 101,
          "question": "Redis 缓存穿透和布隆过滤器的关系",
          "cat1": "中间件",
          "cat2": "缓存"
        }
      ],
      "selected_question_id": 101,
      "fallback_used": false,
      "empty_reason": "",
      "debug_reason": "hybrid_search_ok",
      "error": ""
    }
  ],
  "skill_trace": [
    {
      "skill_name": "project-deep-dive",
      "label": "项目深挖策略",
      "reason": "候选人正在介绍项目，需要追问职责、架构和取舍",
      "persistent": false,
      "status": "loaded"
    }
  ]
}
```

### 兼容字段

旧字段继续写入：

- `metadata.steps`
- `metadata.tool_steps`
- `metadata.thinking`
- `metadata.thinking_duration`
- `metadata.insights`
- `metadata.observability`

前端优先读新字段；没有新字段时回退旧字段。

### 单位约定

- 新字段统一使用 `duration_ms` / `elapsed_ms`。
- 前端格式化为秒或毫秒：
  - `>= 1000ms` 展示 `4.2 秒`
  - `< 1000ms` 展示 `318ms`
- 旧 `thinking_duration` 继续兼容，但实现时应明确转换，避免毫秒当秒显示。

## 后端采集设计

### 统一 trace recorder

在 chat agent 内新增轻量 helper，例如 `trace.py`：

- `record_step(state, step_event)`
- `record_tool_call(state, tool_call, summary, elapsed_ms, output_preview)`
- `record_skill_load(state, skill_name, status, reason, persistent)`
- `build_reasoning_trace(state, collected_thinking, started_at, completed_at)`
- `merge_trace_metadata(metadata, state, collected_events)`

实现也可以先放在 `react_loop.py` / `pipeline.py`，但必须让普通工具路径和 guard 路径复用同一套函数，避免再次漏字段。

### 工具调用覆盖范围

以下路径必须记录 `tool_calls_trace`：

1. 普通 ReAct loop 中的 `load_skill`
2. 普通 ReAct loop 中的 `search_questions`
3. 普通 ReAct loop 中的 `draw_questions`
4. 普通 ReAct loop 中的 `select_question`
5. `force_search_guard` 中执行的 `search_questions` / `draw_questions`
6. 工具验证失败、loop detected、工具返回 error envelope 的失败路径

### 参数脱敏

只保留 allowlist：

```python
SAFE_TOOL_ARG_KEYS = {
    "keywords",
    "count",
    "difficulty",
    "question_type",
    "skill_name",
    "cat1",
    "cat2",
    "candidate_index",
    "question_id",
    "topic",
}
```

其它参数显示为 `<redacted>` 或不写入 metadata。

### 结果预览

工具结果只保存摘要：

- `result_count`
- `result_ids` 前 5 个
- `result_preview` 前 3 个公开题目字段：`id`、`question`、`cat1`、`cat2`、`company`、`round`
- `selected_question_id`
- `fallback_used`
- `empty_reason`
- `debug_reason`
- `error`

不保存 raw output。

### 思考摘要 fallback

当模型没有返回 reasoning content 时，后端根据本轮事件生成公开摘要，不额外调用 LLM：

| 信号 | 摘要句 |
| --- | --- |
| `understanding` step | 分析候选人回答，判断下一步追问方向 |
| `load_skill` | 加载 `{skill_label}`，调整本轮面试策略 |
| `search_questions` | 根据关键词检索题库中的相关面试题 |
| `draw_questions` | 从题库抽取符合当前阶段的题目 |
| `selected_question` | 选择一道题作为本轮追问依据 |
| `generating` | 综合上下文、题库结果和面试阶段组织追问 |
| `closing` | 根据本轮对话生成面试总结 |

`reasoning_trace.source`：

- `model_reasoning`：模型返回 reasoning content
- `summary_fallback`：没有模型 reasoning，但有 steps/tool/skill，可生成公开摘要
- `timing_only`：没有足够事件，只记录耗时

### 耗时计算

`run_chat()` 在 pipeline 开始时记录 `started_at = time.monotonic()`，`done` 时记录总耗时：

- 有模型 thinking session：`reasoning_trace.model_reasoning[*].duration_ms`
- 无模型 thinking：`reasoning_trace.duration_ms = total_elapsed_ms`
- `observability.thinking_duration` 保持与新字段一致，但语义改为“本轮思考/生成可见耗时”，不是 raw CoT 时长。

## SSE 事件设计

保持旧事件不破坏，同时新增可选事件：

```json
{"type":"reasoning_trace_delta","summary":["分析候选人回答"]}
{"type":"tool_call_trace","data":{ "...": "..." }}
{"type":"skill_trace","data":{ "...": "..." }}
```

最低实现可以不新增事件，继续通过现有 `step`、`tool_step`、`thinking`、`done.metadata` 驱动前端；但无论是否新增流式事件，`done.metadata` 和落库 metadata 必须包含完整新字段。

## 前端设计

### 组件职责

继续使用 `ReasoningTimeline.vue`，增强为三层展示：

1. 标题摘要：耗时、工具数、skill 数、步骤数
2. 思考摘要 / 模型显式 reasoning
3. 可点击步骤、工具、skill 详情

如组件过大，可拆分：

- `ReasoningTimeline.vue`
- `ReasoningToolCall.vue`
- `ReasoningSkillItem.vue`
- `ReasoningSummaryBlock.vue`

### 数据读取优先级

`ChatMessage.vue`：

1. 优先读 `metadata.reasoning_trace`
2. 工具优先读 `metadata.tool_calls_trace`
3. skill 优先读 `metadata.skill_trace`
4. 回退旧字段：
   - `metadata.steps`
   - `metadata.tool_steps`
   - `metadata.thinking`
   - `metadata.thinking_duration`
   - `metadata.insights`

### 展开详情

工具详情默认折叠，点击展开。展示字段使用中文标签，内部工程名放在次要位置：

```text
检索题库
工具名 search_questions
参数 keywords=Redis, 缓存
耗时 318ms
结果 3 个
候选题 #101 Redis 缓存穿透...
调试 hybrid_search_ok
```

### 空状态

如果没有 trace，不展示空面板。

如果只有步骤，没有 thinking：

```text
已思考 2.1 秒 · 4 步
```

如果工具失败：

```text
检索题库失败 · 42ms
原因 validation_failed
```

## 持久化与 E2E 契约

所有 assistant message 保存时必须包含完整 trace metadata。验收标准：

1. `POST /api/chat/conversations/{id}/messages` 流式完成后，保存的 assistant message 有 `reasoning_trace`。
2. 如果本轮执行任何工具，保存的 assistant message 有非空 `tool_calls_trace`。
3. 如果本轮加载任何 skill，保存的 assistant message 有非空 `skill_trace`。
4. `GET /api/chat/conversations/{id}/messages` 返回同样字段。
5. 前端刚发送完消息和刷新历史消息后，展示一致。
6. E2E mock SSE 即使只提供旧事件，也能构造并显示兼容 trace；后端 E2E 则验证真实 `run_chat()` done metadata。

## 测试计划

### 后端 RED 测试

1. `run_chat` 普通工具路径：
   - mock `search_questions`
   - 断言 `done.metadata.tool_calls_trace[0].tool_name == "search_questions"`
   - 断言含 `args_summary`、`elapsed_ms`、`result_count`、`result_preview`

2. `force_search_guard` 路径：
   - 让第一轮 LLM 直接给最终文本触发 guard
   - guard 再调用 `search_questions`
   - 断言 `tool_calls_trace` 不为空，旧 `tool_steps` 也不为空

3. skill 加载路径：
   - mock `load_skill(project-deep-dive)`
   - 断言 `skill_trace` 含中文 label、skill_name、status

4. 无模型 reasoning fallback：
   - 只 emit step/tool/done
   - 断言 `reasoning_trace.source == "summary_fallback"`
   - 断言 `reasoning_trace.summary` 非空
   - 断言 `duration_ms >= 0`

5. 模型 reasoning 路径：
   - emit `thinking_start/thinking/thinking_done`
   - 断言 `reasoning_trace.source == "model_reasoning"`
   - 断言 `model_reasoning[*].chunks` 被保存且最多 50 段

6. 路由落库：
   - mock `run_chat` 返回 done metadata
   - 调用 chat route
   - 断言 `chat_service.save_message(... metadata=...)` 保存新字段

### 前端测试

1. mock 历史消息含 `reasoning_trace/tool_calls_trace/skill_trace`，页面显示折叠标题。
2. 点击工具行后显示参数摘要、耗时、结果数、候选题。
3. mock 旧格式 `steps/tool_steps/thinking`，仍能显示兼容面板。
4. mock SSE 流式事件，发送完成后新消息上方显示同样面板。

### 验证命令

后端：

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
```

前端：

```bash
cd frontend && npm run build
cd frontend && npm run test -- chat-thinking-timer.spec.js
```

## 实施顺序

1. 后端先补测试：普通工具、guard 工具、skill、summary fallback。
2. 实现 trace recorder 和 metadata merge。
3. 修 `force_search_guard` 工具 trace 漏记。
4. 修 duration 单位，补 reasoning summary fallback。
5. 前端增强 `ReasoningTimeline.vue`，加可点击工具详情。
6. 补前端 E2E：历史消息和流式消息两种场景。
7. 更新相关 `CLAUDE.md`。

## 风险与取舍

- 原始 CoT 不稳定且不适合直接展示，因此产品层以公开摘要为默认体验。
- 新 metadata 会增大消息体，必须限制 reasoning chunks、result preview 和参数摘要。
- 工具详情过多会影响主聊天阅读，因此第一层只显示用户直觉动作，详情必须点击展开。
- 新字段和旧字段并存一段时间，避免历史消息和现有 E2E 断裂。

## 验收标准

1. 用户真实发起一次需要题库检索的模拟面试后，assistant 消息显示“已思考 N 秒 · 调用 N 个工具 · 加载 N 个策略”。
2. 点击“检索题库”能看到工具名、参数摘要、耗时、结果数和候选题摘要。
3. 触发 `force_search_guard` 的回合也能看到检索工具详情。
4. 刷新页面后历史消息仍显示同样的思考、工具、skill 信息。
5. 后端 E2E 直接检查 done metadata 和落库 message metadata，前端 E2E 检查用户可见面板与点击详情。

# Spec: 模拟面试 Agent 三部分衔接清理

> **位置**: `backend/app/agents/chat/` + `backend/app/mcp_server/`
> **类型**: 技术修复 spec
> **日期**: 2026-07-01
> **状态**: 待实施

## 背景

模拟面试 agent 由三部分组成，衔接链路：

```
ReAct loop (决策层)
  → tools.py (schema + JSON 转发)
    → tool_gateway.py (envelope Pydantic 契约)
      → mcp_server/interview_tools.py (唯一执行层)
        → services/ + session.py 持久化
```

三部分角色分工清晰，但存在 4 处衔接缝隙，违反 `mcp_server/CLAUDE.md` 写的契约。

## 问题清单

### 问题 1: `tools.py:_execute_select_question` 业务逻辑泄漏

**现状** (`backend/app/agents/chat/tools.py:299-347`):

`_execute_select_question` 有 60 行业务逻辑：
- 候选越界检查（`INDEX_OUT_OF_RANGE`）
- 空候选 envelope 构造（`NO_CANDIDATES`）
- 然后才调 `select_question_tool(force_candidate=selected)`

**违反契约**: `mcp_server/CLAUDE.md` 写"`tools.py` 不应直接组装搜索或抽题 envelope"。其他 3 个工具（load_skill/search/draw）都是纯转发，唯独 select 有 60 行业务逻辑。

**后果**: 双入口错误码不一致
- 内部 ReAct 路径: `NO_CANDIDATES` / `INDEX_OUT_OF_RANGE`
- 外部 MCP 路径 (`app.py:select_question`): `NO_CANDIDATE`（无越界检查）

### 问题 2: `load_skill_tool` envelope 不走统一构造

**现状** (`backend/app/mcp_server/interview_tools.py:39-92`):

`load_skill_tool` 直接 hand-craft dict 返回，不经过 `build_success_envelope` / `build_error_envelope`。对比 `search_questions_tool` / `draw_questions_tool` / `select_question_tool` 都用统一构造。

**违反契约**: `mcp_server/CLAUDE.md` 写"所有工具返回统一 envelope，包括 load_skill"。

**后果**:
- `load_skill` envelope 缺少 `metadata.metrics`（ToolMetrics）
- 缺少 `debug_reason`
- 字段不经 Pydantic 校验，手写字典容易漂移

### 问题 3: 双入口 session 持久化策略差异未文档化

**现状**:

| 入口 | state 来源 | session 持久化 |
|---|---|---|
| 内部 ReAct (`tools.py`) | `ChatState` TypedDict，pipeline 内存流转 | 不显式持久化 |
| 外部 MCP (`app.py`) | `_init_tool_state` 从 `load_mcp_session` 加载 | `save_mcp_session` 持久化到 Redis/SQLite |

**风险**:
- 内部 ReAct 中途崩溃，`active_skills` / `retrieved_questions` 丢失
- 外部 MCP client 分步调用（load_skill → draw_questions → select_question）依赖 session 持久化
- CLAUDE.md 未说明这个差异，新人维护易混淆

### 问题 4: 工具调用和 thinking 内容不持久化到消息历史（用户痛点）

**已确认**（explore 调查结果）:

**后端持久化**（`chat.py:306-336` 在 `done` 事件时调 `save_message`）:
- `content`: **只保存最终 assistant 文本**（accumulated chunk events，去掉 `[BASIS]` tags）
- `metadata`: 由 `_build_react_metadata()`（`metadata.py:154-286`）构造，包含：
  - `basis_type`, `basis_question_ids`, `basis_confidence`, `should_show_references`
  - `active_skills`, `asked_question_text`
  - `retrieved_questions` (top 3), `selected_basis_questions`, `candidate_questions`
  - `selected_question`, `question_source`, `question_source_reason`
  - `question_plan`
  - `resume_ref`, `jd_ref`

**未持久化**（只走 SSE 流式，然后丢失）:
- `thinking_start` / `thinking` / `thinking_done` 事件 — thinking 内容和时长
- `step` 事件 — 工具执行进度（load_skill/search_questions/draw_questions/select_question）
- `insight` 事件 — 决策解释
- `retrieved` 事件 — 完整搜索/抽题结果（metadata 里只有 top 3 子集）
- 工具调用 payload — LLM tool_calls 的 function name + arguments

**前端持久化**（`ChatView.vue:806-868` 客户端内存）:
前端在流式过程中累积 thinking/steps/insights 到 reactive refs，流结束后 push 到 `messages.value`（带 enriched metadata）。但这个 enriched message **从不发回后端**——纯 Vue 内存状态，页面刷新即丢失。

**用户痛点**: e2e 测试或页面刷新后，`getMessages()` 返回后端版本，缺少 thinking 内容、工具调用步骤、insights —— 这就是"前端不保存工具调用和思考时间内容"的根因。

**DB schema 限制** (`db/migrations/chat.py:37-48`): `chat_messages` 表只有 `id`, `conversation_id`, `role`, `content`, `token_count`, `metadata` (TEXT/JSON), `created_at`。没有专门的 `tool_calls` 或 `thinking` 列。

## 修复方案

### 修复 1: select_question 业务逻辑下沉到 mcp_server

**目标**: `tools.py:_execute_select_question` 变成纯转发，与其他 3 个工具一致。

**改动**:

1. `mcp_server/interview_tools.py:select_question_tool` 增加 `candidate_index` 参数和越界检查逻辑（从 `tools.py` 迁移）:

```python
def select_question_tool(
    args: dict,
    state: ChatState,
    *,
    force_candidate: dict | None = None,
    candidate_index: int | None = None,  # 新增
) -> dict:
    candidates = (
        args.get("candidates")
        or state.get("candidate_questions")
        or state.get("retrieved_questions")
        or []
    )

    # 越界检查（从 tools.py 迁移）
    if not candidates:
        return build_error_envelope(
            tool="select_question",
            error_code="NO_CANDIDATES",
            message="No candidate questions available to select",
            total_ms=0,
            debug_reason="no_candidates",
            empty_reason="no_candidates",
        )

    if candidate_index is not None:
        if not isinstance(candidate_index, int) or candidate_index < 0 or candidate_index >= len(candidates):
            return build_error_envelope(
                tool="select_question",
                error_code="INDEX_OUT_OF_RANGE",
                message=f"candidate_index {candidate_index} is out of range (0-{len(candidates) - 1})",
                total_ms=0,
                debug_reason="index_out_of_range",
                empty_reason="index_out_of_range",
            )
        force_candidate = candidates[candidate_index]

    # ... 原有 _maybe_create_question_plan 逻辑
```

2. `tools.py:_execute_select_question` 简化为纯转发（不超过 10 行）:

```python
def _execute_select_question(args: dict, state: ChatState) -> str:
    from app.mcp_server.interview_tools import select_question_tool

    candidate_index = args.get("candidate_index", 0)
    envelope = select_question_tool(args, state, candidate_index=candidate_index)
    return json.dumps(envelope, ensure_ascii=False)
```

3. `app.py:select_question` MCP 工具也支持 `candidate_index` 参数（统一双入口）。

**错误码统一**: `NO_CANDIDATES`（保留现有 tools.py 用法）+ `INDEX_OUT_OF_RANGE`。

### 修复 2: load_skill envelope 走统一构造

**目标**: `load_skill_tool` 返回结构与其他 3 个工具一致。

**前置改动**: `tool_gateway.py:ToolName` Literal 加上 `"load_skill"`:

```python
ToolName = Literal["search_questions", "draw_questions", "select_question", "load_skill"]
```

**主改动** (`mcp_server/interview_tools.py:load_skill_tool`):

```python
def load_skill_tool(args: dict, state: ChatState, registry_getter=None) -> dict:
    started = time.monotonic()
    skill_name = args.get("skill_name", "")
    registry = (registry_getter or _get_default_skill_registry)()
    skill = registry.get(skill_name)

    if skill is None:
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="load_skill",
            error_code="UNKNOWN_SKILL",
            message=f"Unknown skill: {skill_name}",
            total_ms=total_ms,
            debug_reason="unknown_skill",
        )

    active_skills = state.setdefault("active_skills", [])
    if skill_name in active_skills:
        total_ms = int((time.monotonic() - started) * 1000)
        envelope = build_success_envelope(
            tool="load_skill",
            items=[],
            total_ms=total_ms,
            debug_reason="already_active",
        )
        envelope["metadata"]["status"] = "already_active"
        envelope["metadata"]["skill"] = skill_name
        envelope["metadata"]["summary"] = f"技能「{skill.description}」已在激活状态。"
        return envelope

    active_skills.append(skill_name)
    instruction = skill.get_instruction()
    if instruction:
        state.setdefault("active_skill_instructions", []).append(
            {"skill_name": skill_name, "instruction": instruction}
        )

    total_ms = int((time.monotonic() - started) * 1000)
    envelope = build_success_envelope(
        tool="load_skill",
        items=[],
        total_ms=total_ms,
        debug_reason="loaded",
    )
    envelope["metadata"]["status"] = "loaded"
    envelope["metadata"]["skill"] = skill_name
    envelope["metadata"]["summary"] = f"技能「{skill.description}」已激活，将注入到当前 ReAct loop 的系统提示中。"
    return envelope
```

### 修复 3: 双入口 session 策略统一

**方案 A（推荐）**: 内部 ReAct 也走 session 持久化。

- `pipeline.py` 在 ReAct 循环结束后（`_persist_active_skills` 已有）增加 `save_mcp_session` 调用
- 需要从 ChatState 提取 session_id（新增字段或从 conversation_id 派生）
- 只在 ReAct 循环结束时持久化，不在每次工具执行后（避免性能开销）

**方案 B（轻量）**: 仅文档化差异，不改持久化逻辑。

- 在 `mcp_server/CLAUDE.md` 增加"双入口策略"章节
- 说明内部 ReAct 的 state 由 pipeline 流转，崩溃丢失可接受
- 外部 MCP 才需要 session 持久化

**推荐方案 A**，因为：
1. 崩溃恢复场景真实存在（长程面试中途 backend 重启）
2. 与外部 MCP 路径统一，减少认知负担
3. `save_mcp_session` 已有白名单过滤，性能开销小

### 修复 4: 工具调用和 thinking 内容持久化到消息历史

**方案 A（推荐 - metadata 扩展）**: 在 `done` 事件的 metadata 里增加 `thinking`、`steps`、`insights` 字段。

**改动**:

1. `pipeline.py:_run_pipeline()` 增加累积器（在闭包里）:

```python
# 在 _run_pipeline 闭包里
collected_steps: list[dict] = []
collected_insights: list[dict] = []
collected_thinking: list[dict] = []
thinking_start_time: float | None = None

# 在 event 处理循环里
if event_type == "step":
    collected_steps.append(event.get("data", {}))
elif event_type == "insight":
    collected_insights.append(event.get("data", {}))
elif event_type == "thinking_start":
    thinking_start_time = time.monotonic()
    collected_thinking.append({"start": event.get("data", {})})
elif event_type == "thinking":
    collected_thinking[-1].setdefault("chunks", []).append(event.get("data", {}).get("text", ""))
elif event_type == "thinking_done":
    if thinking_start_time:
        collected_thinking[-1]["duration_ms"] = int((time.monotonic() - thinking_start_time) * 1000)
        thinking_start_time = None
```

2. `pipeline.py` 在 `done` 事件时，把这些累积器合并进 metadata:

```python
elif event_type == "done":
    metadata = _build_react_metadata(state)
    metadata["thinking"] = collected_thinking
    metadata["thinking_duration"] = sum(t.get("duration_ms", 0) for t in collected_thinking)
    metadata["steps"] = collected_steps
    metadata["insights"] = collected_insights
    yield {"type": "done", "metadata": metadata, "content": full_response}
```

3. 前端 `getMessages()` 返回的 metadata 自动包含这些字段，前端 ChatView.vue 渲染时直接用后端版本（去掉前端 enriched 逻辑，或保留为 fallback）。

**方案 B（重 - 独立 trace 表）**: 创建 `chat_message_traces` 表，存完整事件流。

```sql
CREATE TABLE chat_message_traces (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,  -- thinking_start/thinking/thinking_done/step/insight/retrieved
    content TEXT NOT NULL,     -- JSON
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (message_id) REFERENCES chat_messages(id)
);
```

**推荐方案 A**，因为：
1. 不需要 schema 迁移（metadata 已是 JSON 列）
2. 前端无需改 API 调用
3. thinking/steps/insights 数据量小，放进 metadata 可接受
4. 方案 B 适合完整审计追踪，但当前需求只是"刷新后能看到 thinking"

## 验收标准

- [ ] `tools.py:_execute_select_question` 不超过 10 行（纯转发）
- [ ] `select_question_tool` 支持参数化 `candidate_index`，双入口错误码一致
- [ ] `load_skill_tool` 使用 `build_success_envelope` / `build_error_envelope`
- [ ] `ToolName` Literal 包含 `"load_skill"`
- [ ] `load_skill` envelope 包含 `metadata.metrics.total_ms` 和 `debug_reason`
- [ ] 内部 ReAct 路径调 `save_mcp_session`（方案 A）或 CLAUDE.md 文档化差异（方案 B）
- [ ] `done` 事件 metadata 包含 `thinking`、`steps`、`insights` 字段（修复 4）
- [ ] 页面刷新后，前端从 `getMessages()` 能取回 thinking 内容和工具调用步骤
- [ ] 现有测试全绿: `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`
- [ ] 新增测试覆盖:
  - select_question 越界（`INDEX_OUT_OF_RANGE` + `NO_CANDIDATES`）
  - load_skill envelope 结构（含 metrics + debug_reason）
  - session 持久化（方案 A）
  - thinking/steps/insights 持久化到 metadata（修复 4）
- [ ] `mcp_server/CLAUDE.md` 更新双入口策略说明
- [ ] `agents/chat/CLAUDE.md` 更新 tools.py 职责说明（纯转发）

## 实施顺序

1. **修复 2（load_skill envelope）** — 最小改动，先统一契约，扩展 ToolName Literal
2. **修复 1（select_question 下沉）** — 依赖修复 2 的 ToolName 扩展
3. **修复 4（thinking/steps 持久化）** — 独立改动，解决用户痛点
4. **修复 3（session 持久化）** — 独立改动，可并行

## 测试要求

- TDD：每个修复先写失败测试
- 测试文件:
  - `backend/tests/chat/test_tools.py` — tools.py 转发逻辑
  - `backend/tests/chat/test_interview_mcp_tools.py` — interview_tools 执行层
  - `backend/tests/chat/test_mcp_session.py` — session 持久化
  - `backend/tests/chat/test_chat.py` — 消息持久化（修复 4 新增）
  - `backend/tests/chat/test_react_loop.py` — ReAct 事件累积（修复 4 新增）
- 运行命令: `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`

## 风险

- **修复 1**: select_question 错误码从 `NO_CANDIDATE` 变 `NO_CANDIDATES`，需检查前端是否硬编码错误码
- **修复 3 方案 A**: 内部 ReAct 增加 session 持久化，可能影响性能。建议只在 ReAct 循环结束时持久化，不在每次工具执行后
- **修复 4 方案 A**: thinking 内容可能包含 LLM 内部推理，持久化到 DB 有隐私风险（用户可看到 AI 思考过程）。需确认产品需求
- **修复 4 方案 A**: metadata 字段膨胀，长面试可能 metadata JSON 过大。建议限制 thinking chunks 数量或只存摘要

## 参考文件

- `backend/app/agents/chat/CLAUDE.md` — chat agent 架构
- `backend/app/mcp_server/CLAUDE.md` — MCP 边界契约
- `backend/app/agents/chat/tools.py` — ReAct tool schema + 转发层
- `backend/app/agents/chat/tool_gateway.py` — envelope Pydantic 契约
- `backend/app/mcp_server/interview_tools.py` — 唯一执行层
- `backend/app/mcp_server/session.py` — session 持久化
- `backend/app/mcp_server/app.py` — 外部 MCP 入口
- `backend/app/agents/chat/pipeline.py` — ReAct pipeline + 事件流
- `backend/app/agents/chat/metadata.py` — `_build_react_metadata()`
- `backend/app/agents/chat/react_loop.py` — ReAct 循环 + 事件发射
- `backend/app/routers/chat.py` — SSE 路由 + 持久化决策点
- `backend/app/services/chat_service.py:save_message` — DB 持久化
- `backend/app/db/migrations/chat.py` — chat_messages schema
- `frontend/src/components/business/ChatView.vue` — 前端 SSE 处理 + 内存累积

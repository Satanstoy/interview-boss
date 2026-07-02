# Chat Reasoning Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a DS-style chat reasoning panel that shows public reasoning summaries, clickable tool-call details, skill loading details, and persists the same trace data for live SSE, history reloads, backend E2E, and real user runs.

**Architecture:** Add a backend trace normalization layer under `backend/app/agents/chat/trace.py`, then feed it from `react_loop.py` and `pipeline.py` so every ReAct path produces `reasoning_trace`, `tool_calls_trace`, and `skill_trace` in assistant message metadata. Enhance the existing frontend `ReasoningTimeline.vue` instead of adding a separate surface, with `ChatMessage.vue` and `ChatView.vue` normalizing new and legacy metadata into the same display contract.

**Tech Stack:** Python 3.10 / FastAPI / pytest through Docker test-runtime; Vue 3 Composition API / Vite / Playwright; existing SSE chat API and message metadata JSON.

## Global Constraints

- Do not display hidden raw CoT. Show only model-explicit reasoning content or backend-generated public reasoning summaries.
- Tool details must be intuitive at the first layer and technical only after click expansion.
- All assistant messages produced by chat must persist trace metadata; live post-send and history reload must render from the same contract.
- Preserve legacy `steps`, `tool_steps`, `thinking`, `thinking_duration`, `insights`, and `observability` fields for compatibility.
- New duration fields use milliseconds: `duration_ms` and `elapsed_ms`; frontend formats them for humans.
- Tool args and outputs are allowlisted summaries only; no raw tool args, full tool output, full skill instruction, API key, resume text, or JD text in metadata.
- Use Docker for backend pytest in this repo.
- Update relevant `CLAUDE.md` files after implementation changes.

---

## File Structure

- Create `backend/app/agents/chat/trace.py`
  - Owns trace labels, safe arg summarization, tool result preview, skill trace records, reasoning summary fallback, and merge helpers.
- Modify `backend/app/agents/chat/react_loop.py`
  - Records every ordinary tool call and every `force_search_guard` tool call through the same trace helper.
- Modify `backend/app/agents/chat/pipeline.py`
  - Builds `reasoning_trace`, carries `tool_calls_trace` / `skill_trace` into `done.metadata`, keeps legacy fields synchronized, and fixes duration semantics.
- Modify `backend/app/agents/chat/CLAUDE.md`
  - Documents the new trace metadata contract and implementation boundary.
- Modify `backend/tests/chat/test_chat.py`
  - Adds backend metadata tests for reasoning fallback, model reasoning, tool trace, and skill trace.
- Modify `backend/tests/chat/test_react_loop.py`
  - Adds `force_search_guard` trace coverage where the current bug lives.
- Modify `frontend/src/components/business/ReasoningTimeline.vue`
  - Renders DS-style header, public reasoning summary, clickable tool details, and skill details.
- Modify `frontend/src/components/business/ChatMessage.vue`
  - Normalizes new metadata and legacy metadata into `ReasoningTimeline` props.
- Modify `frontend/src/components/business/ChatView.vue`
  - Builds compatible live message metadata after SSE completion and passes live trace props while streaming.
- Modify `frontend/src/components/business/CLAUDE.md`
  - Documents the enhanced reasoning timeline responsibilities.
- Modify `frontend/tests/e2e/chat-thinking-timer.spec.js`
  - Adds coverage for history rendering and clickable tool details.

---

### Task 1: Backend Trace Helper And Metadata Unit Tests

**Files:**
- Create: `backend/app/agents/chat/trace.py`
- Test: `backend/tests/chat/test_chat.py`

**Interfaces:**
- Produces: `safe_tool_args(tool_call: dict) -> dict`
- Produces: `build_tool_trace(tool_name: str, tool_call: dict, summary: dict, elapsed_ms: int, state: dict, output: str = "") -> dict`
- Produces: `build_skill_trace_from_tool(tool_name: str, tool_call: dict, summary: dict) -> dict | None`
- Produces: `build_reasoning_trace(collected_thinking: list[dict], steps: list[dict], tool_traces: list[dict], skill_traces: list[dict], duration_ms: int) -> dict`
- Produces: `merge_trace_metadata(metadata: dict, *, reasoning_trace: dict, tool_calls_trace: list[dict], skill_trace: list[dict]) -> dict`
- Consumes: Existing `tool_call` shape from `react_loop.py`, existing tool envelope JSON strings, and `ChatState` dict.

- [ ] **Step 1: Write failing tests for trace helper behavior**

Append these tests to `backend/tests/chat/test_chat.py`:

```python
class TestReasoningTraceHelpers:
    def test_safe_tool_args_keeps_only_public_fields(self):
        from app.agents.chat.trace import safe_tool_args

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps(
                    {
                        "keywords": ["Redis", "缓存"],
                        "question_type": "knowledge_probe",
                        "secret": "must-not-leak",
                    },
                    ensure_ascii=False,
                ),
            }
        }

        assert safe_tool_args(tool_call) == {
            "keywords": ["Redis", "缓存"],
            "question_type": "knowledge_probe",
        }

    def test_build_tool_trace_keeps_result_preview_and_labels(self):
        from app.agents.chat.trace import build_tool_trace

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": ["Redis"]}, ensure_ascii=False),
            }
        }
        state = {
            "retrieved_questions": [
                {
                    "id": 101,
                    "question": "Redis 缓存穿透怎么处理？",
                    "cat1": "中间件",
                    "cat2": "缓存",
                    "sources": [{"company": "腾讯", "round": "一面"}],
                }
            ],
            "selected_question": {"id": 101},
        }
        summary = {
            "ok": True,
            "result_count": 1,
            "result_ids": [101],
            "fallback_used": False,
            "debug_reason": "hybrid_search_ok",
        }

        trace = build_tool_trace(
            "search_questions",
            tool_call,
            summary,
            elapsed_ms=318,
            state=state,
        )

        assert trace["tool_name"] == "search_questions"
        assert trace["label"] == "检索题库"
        assert trace["args_summary"] == {"keywords": ["Redis"]}
        assert trace["elapsed_ms"] == 318
        assert trace["result_count"] == 1
        assert trace["result_ids"] == [101]
        assert trace["result_preview"][0]["question"] == "Redis 缓存穿透怎么处理？"
        assert trace["result_preview"][0]["company"] == "腾讯"
        assert trace["selected_question_id"] == 101
        assert trace["debug_reason"] == "hybrid_search_ok"

    def test_build_skill_trace_from_load_skill_tool(self):
        from app.agents.chat.trace import build_skill_trace_from_tool

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "project-deep-dive"}),
            }
        }

        trace = build_skill_trace_from_tool(
            "load_skill",
            tool_call,
            {"ok": True},
        )

        assert trace == {
            "skill_name": "project-deep-dive",
            "label": "项目深挖策略",
            "reason": "候选人正在介绍项目，需要追问职责、架构和取舍",
            "persistent": False,
            "status": "loaded",
        }

    def test_build_reasoning_trace_uses_summary_fallback_without_model_reasoning(self):
        from app.agents.chat.trace import build_reasoning_trace

        reasoning = build_reasoning_trace(
            collected_thinking=[],
            steps=[
                {"step": "understanding", "message": "正在分析你的回答..."},
                {"step": "search_questions", "message": "正在检索相关面试题..."},
                {"step": "generating", "message": "正在生成回答..."},
            ],
            tool_traces=[],
            skill_traces=[],
            duration_ms=2400,
        )

        assert reasoning["version"] == 1
        assert reasoning["duration_ms"] == 2400
        assert reasoning["source"] == "summary_fallback"
        assert reasoning["summary"] == [
            "分析候选人回答，判断下一步追问方向",
            "根据关键词检索题库中的相关面试题",
            "综合上下文、题库结果和面试阶段组织追问",
        ]
        assert reasoning["model_reasoning"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_chat.py::TestReasoningTraceHelpers -q
```

Expected: FAIL because `app.agents.chat.trace` does not exist.

- [ ] **Step 3: Implement `backend/app/agents/chat/trace.py`**

Create `backend/app/agents/chat/trace.py`:

```python
"""Public reasoning/tool trace helpers for chat message metadata."""

from __future__ import annotations

import json
from typing import Any

from app.agents.chat.metadata import _extract_company, _extract_round

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

TOOL_LABELS = {
    "load_skill": "加载策略",
    "search_questions": "检索题库",
    "draw_questions": "抽取题目",
    "select_question": "采用面试题",
}

SKILL_LABELS = {
    "adaptive-difficulty": "自适应难度策略",
    "algorithm-coding": "算法面试策略",
    "hr-soft-skills": "HR 软技能策略",
    "interview-rhythm": "面试节奏策略",
    "project-deep-dive": "项目深挖策略",
    "system-design": "系统设计策略",
    "theory-qa": "理论问答策略",
}

SKILL_REASONS = {
    "adaptive-difficulty": "根据候选人的回答质量调整追问难度",
    "algorithm-coding": "当前阶段需要考察手撕代码和算法思路",
    "hr-soft-skills": "当前阶段需要考察行为面和稳定性信号",
    "interview-rhythm": "根据面试进度调整本轮追问节奏",
    "project-deep-dive": "候选人正在介绍项目，需要追问职责、架构和取舍",
    "system-design": "当前阶段需要考察系统设计和场景题能力",
    "theory-qa": "当前阶段需要考察基础知识和技术原理",
}

PERSISTENT_SKILL_NAMES = {"interview-rhythm"}

SUMMARY_BY_STEP = {
    "understanding": "分析候选人回答，判断下一步追问方向",
    "load_skill": "加载面试策略，调整本轮追问方式",
    "search_questions": "根据关键词检索题库中的相关面试题",
    "draw_questions": "从题库抽取符合当前阶段的题目",
    "select_question": "选择一道题作为本轮追问依据",
    "force_search_guard": "补充检索题库，确保追问有题库依据",
    "generating": "综合上下文、题库结果和面试阶段组织追问",
    "closing": "根据本轮对话生成面试总结",
}


def _parse_tool_args(tool_call: dict) -> dict:
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    if isinstance(raw_args, dict):
        return raw_args
    try:
        parsed = json.loads(raw_args or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:120]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:5]]
    if isinstance(value, dict):
        return {
            str(key)[:40]: _safe_value(item)
            for key, item in list(value.items())[:5]
        }
    return str(type(value).__name__)


def safe_tool_args(tool_call: dict) -> dict:
    args = _parse_tool_args(tool_call)
    return {
        key: _safe_value(value)
        for key, value in args.items()
        if key in SAFE_TOOL_ARG_KEYS
    }


def _preview_question(question: dict) -> dict:
    return {
        "id": question.get("id"),
        "question": str(question.get("question") or "")[:160],
        "cat1": question.get("cat1") or "",
        "cat2": question.get("cat2") or "",
        "company": _extract_company(question),
        "round": _extract_round(question),
    }


def _question_candidates(state: dict) -> list[dict]:
    candidates = state.get("retrieved_questions") or state.get("candidate_questions") or []
    return [item for item in candidates if isinstance(item, dict)]


def _selected_question_id(state: dict):
    selected = state.get("selected_question")
    if isinstance(selected, dict):
        return selected.get("id")
    return None


def build_tool_trace(
    tool_name: str,
    tool_call: dict,
    summary: dict,
    elapsed_ms: int,
    state: dict,
    output: str = "",
) -> dict:
    result_preview = [_preview_question(q) for q in _question_candidates(state)[:3]]
    result_ids = summary.get("result_ids")
    if not isinstance(result_ids, list):
        result_ids = [
            q.get("id")
            for q in _question_candidates(state)[:5]
            if q.get("id") is not None
        ]
    error = summary.get("error") or ""
    ok = bool(summary.get("ok", not error))
    return {
        "tool_name": tool_name,
        "label": TOOL_LABELS.get(tool_name, tool_name),
        "message": str(summary.get("message") or ""),
        "args_summary": safe_tool_args(tool_call),
        "elapsed_ms": max(int(elapsed_ms or 0), 0),
        "ok": ok,
        "result_count": int(summary.get("result_count") or 0),
        "result_ids": result_ids[:5],
        "result_preview": result_preview,
        "selected_question_id": _selected_question_id(state),
        "fallback_used": bool(summary.get("fallback_used", False)),
        "empty_reason": str(summary.get("empty_reason") or ""),
        "debug_reason": str(summary.get("debug_reason") or ""),
        "error": str(error),
    }


def build_skill_trace_from_tool(
    tool_name: str,
    tool_call: dict,
    summary: dict,
) -> dict | None:
    if tool_name != "load_skill":
        return None
    skill_name = str(safe_tool_args(tool_call).get("skill_name") or "")
    if not skill_name:
        return None
    status = "loaded" if summary.get("ok", True) else "error"
    if summary.get("error"):
        status = str(summary["error"])
    return {
        "skill_name": skill_name,
        "label": SKILL_LABELS.get(skill_name, skill_name),
        "reason": SKILL_REASONS.get(skill_name, "根据本轮面试阶段加载对应策略"),
        "persistent": skill_name in PERSISTENT_SKILL_NAMES,
        "status": status,
    }


def build_reasoning_trace(
    collected_thinking: list[dict],
    steps: list[dict],
    tool_traces: list[dict],
    skill_traces: list[dict],
    duration_ms: int,
) -> dict:
    model_reasoning = []
    for item in collected_thinking:
        chunks = [
            str(chunk)
            for chunk in item.get("chunks", [])
            if str(chunk).strip()
        ][:50]
        if chunks:
            model_reasoning.append(
                {
                    "chunks": chunks,
                    "duration_ms": max(int(item.get("duration_ms") or 0), 0),
                    "truncated": len(item.get("chunks", [])) > 50,
                }
            )

    summary = []
    seen = set()
    for step in steps:
        text = SUMMARY_BY_STEP.get(step.get("step"))
        if text and text not in seen:
            summary.append(text)
            seen.add(text)
    for skill in skill_traces:
        label = skill.get("label") or skill.get("skill_name")
        if label:
            text = f"加载{label}，调整本轮面试策略"
            if text not in seen:
                summary.append(text)
                seen.add(text)
    for tool in tool_traces:
        label = tool.get("label")
        if label:
            text = f"{label}，获取本轮追问依据"
            if text not in seen:
                summary.append(text)
                seen.add(text)

    if model_reasoning:
        source = "model_reasoning"
    elif summary:
        source = "summary_fallback"
    else:
        source = "timing_only"

    return {
        "version": 1,
        "duration_ms": max(int(duration_ms or 0), 0),
        "source": source,
        "summary": summary[:8],
        "model_reasoning": model_reasoning,
    }


def merge_trace_metadata(
    metadata: dict,
    *,
    reasoning_trace: dict,
    tool_calls_trace: list[dict],
    skill_trace: list[dict],
) -> dict:
    merged = dict(metadata or {})
    merged["reasoning_trace"] = reasoning_trace
    merged["tool_calls_trace"] = tool_calls_trace
    merged["skill_trace"] = skill_trace
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_chat.py::TestReasoningTraceHelpers -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/trace.py backend/tests/chat/test_chat.py
git commit -m "feat(chat): add reasoning trace helpers"
```

---

### Task 2: Backend Pipeline Metadata Merge

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`
- Test: `backend/tests/chat/test_chat.py`

**Interfaces:**
- Consumes: `build_reasoning_trace(...)` and `merge_trace_metadata(...)` from Task 1.
- Produces: `done.metadata.reasoning_trace`, `done.metadata.tool_calls_trace`, `done.metadata.skill_trace`.
- Produces: legacy `thinking_duration` in seconds for frontend compatibility.

- [ ] **Step 1: Write failing tests for run_chat metadata**

Append to `backend/tests/chat/test_chat.py`:

```python
class TestRunChatReasoningTraceMetadata:
    async def test_done_metadata_includes_summary_fallback_reasoning_trace(self):
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {"type": "chunk", "content": "Answer"},
            {"type": "done", "metadata": {}},
        ]

        with (
            patch("app.agents.chat.pipeline._step_load_context", new_callable=AsyncMock),
            patch("app.agents.chat.pipeline._step_classify", new_callable=AsyncMock),
            patch(
                "app.agents.chat.pipeline._react_loop",
                side_effect=lambda state: _async_gen(react_events),
            ),
            patch(
                "app.agents.chat.pipeline._build_react_metadata",
                return_value=({}, "Answer"),
            ),
            patch("app.agents.chat.pipeline._basis_event_payload", return_value={}),
            patch("app.agents.chat.pipeline._persist_active_skills", new_callable=AsyncMock),
            patch("app.agents.chat.pipeline._step_extract_memory", new_callable=AsyncMock),
        ):
            done_event = None
            async for event in run_chat("conv-1", 1, "Hello", mode="free_practice"):
                if event.get("type") == "done":
                    done_event = event

        metadata = done_event["metadata"]
        assert metadata["reasoning_trace"]["version"] == 1
        assert metadata["reasoning_trace"]["source"] in {"summary_fallback", "timing_only"}
        assert metadata["reasoning_trace"]["duration_ms"] >= 0
        assert metadata["tool_calls_trace"] == []
        assert metadata["skill_trace"] == []

    async def test_done_metadata_includes_model_reasoning_trace(self):
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {"type": "thinking_start", "content": ""},
            {"type": "thinking", "content": "思考内容"},
            {"type": "thinking_done", "duration": 1.2, "content": "思考内容"},
            {"type": "chunk", "content": "Answer"},
            {"type": "done", "metadata": {}},
        ]

        with (
            patch("app.agents.chat.pipeline._step_load_context", new_callable=AsyncMock),
            patch("app.agents.chat.pipeline._step_classify", new_callable=AsyncMock),
            patch(
                "app.agents.chat.pipeline._react_loop",
                side_effect=lambda state: _async_gen(react_events),
            ),
            patch(
                "app.agents.chat.pipeline._build_react_metadata",
                return_value=({}, "Answer"),
            ),
            patch("app.agents.chat.pipeline._basis_event_payload", return_value={}),
            patch("app.agents.chat.pipeline._persist_active_skills", new_callable=AsyncMock),
            patch("app.agents.chat.pipeline._step_extract_memory", new_callable=AsyncMock),
        ):
            done_event = None
            async for event in run_chat("conv-1", 1, "Hello", mode="free_practice"):
                if event.get("type") == "done":
                    done_event = event

        trace = done_event["metadata"]["reasoning_trace"]
        assert trace["source"] == "model_reasoning"
        assert trace["model_reasoning"][0]["chunks"] == ["思考内容"]
        assert trace["duration_ms"] >= trace["model_reasoning"][0]["duration_ms"]
        assert done_event["metadata"]["thinking_duration"] >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_chat.py::TestRunChatReasoningTraceMetadata -q
```

Expected: FAIL because `reasoning_trace` is not populated.

- [ ] **Step 3: Update `pipeline.py` metadata merge**

In `backend/app/agents/chat/pipeline.py`, import helpers:

```python
from app.agents.chat.trace import build_reasoning_trace, merge_trace_metadata
```

In `run_chat()`, before the event loop, add:

```python
run_started_at = time.monotonic()
```

Inside the `elif item_type == "thinking_start"` branch, keep appending a thinking record, but preserve content shape:

```python
collected_thinking.append({"chunks": []})
```

Inside the `elif item_type == "thinking_done"` branch, prefer the event duration when present and store milliseconds:

```python
duration = item.get("duration")
if duration is not None:
    collected_thinking[-1]["duration_ms"] = int(float(duration) * 1000)
elif collected_thinking and thinking_start_time:
    collected_thinking[-1]["duration_ms"] = int((time.monotonic() - thinking_start_time) * 1000)
thinking_start_time = None
```

Inside the `elif item_type == "done"` branch, before assigning legacy fields:

```python
total_duration_ms = int((time.monotonic() - run_started_at) * 1000)
tool_trace = state.get("tool_calls_trace", [])
skill_trace = state.get("skill_trace", [])
reasoning_trace = build_reasoning_trace(
    collected_thinking,
    collected_steps,
    tool_trace,
    skill_trace,
    total_duration_ms,
)
metadata = merge_trace_metadata(
    metadata,
    reasoning_trace=reasoning_trace,
    tool_calls_trace=tool_trace,
    skill_trace=skill_trace,
)
```

Then keep legacy fields, but set `thinking_duration` in seconds:

```python
metadata["thinking_duration"] = round(reasoning_trace["duration_ms"] / 1000, 1)
metadata["tool_steps"] = collected_tool_steps or state.get("tool_steps", [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_chat.py::TestRunChatReasoningTraceMetadata -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/pipeline.py backend/tests/chat/test_chat.py
git commit -m "feat(chat): persist reasoning trace metadata"
```

---

### Task 3: Tool And Skill Trace In ReAct Paths

**Files:**
- Modify: `backend/app/agents/chat/react_loop.py`
- Test: `backend/tests/chat/test_react_loop.py`
- Test: `backend/tests/chat/test_chat.py`

**Interfaces:**
- Consumes: `build_tool_trace(...)` and `build_skill_trace_from_tool(...)`.
- Produces: `state["tool_calls_trace"]`, `state["skill_trace"]`, and legacy `state["tool_steps"]`.
- Fixes: `force_search_guard` must record the same trace as ordinary `search_questions` / `draw_questions`.

- [ ] **Step 1: Write failing test for guard tool trace**

Append to `backend/tests/chat/test_react_loop.py`:

```python
class TestForceSearchGuardTrace:
    async def test_force_search_guard_records_tool_trace(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "conv-guard-trace",
            "user_id": 1,
            "user_message": "我负责 Redis 缓存优化。",
            "intent": "interview_question",
            "answer_complete": True,
            "mode": "free_practice",
            "message_history": [
                {"role": "assistant", "content": "请介绍项目。"},
                {"role": "user", "content": "我负责 Redis 缓存优化。"},
            ],
            "recent_messages": [],
            "retrieved_questions": [],
            "candidate_questions": [],
            "active_skills": [],
            "tool_steps": [],
        }

        search_results = [
            {
                "id": 101,
                "question": "Redis 缓存穿透怎么处理？",
                "cat1": "中间件",
                "cat2": "缓存",
                "sources": [{"company": "腾讯", "round": "一面"}],
            }
        ]

        llm_responses = [
            {"content": "直接追问一句。", "tool_calls": None, "finish_reason": "stop"},
            {
                "content": None,
                "tool_calls": [_tc("search_questions", {"keywords": ["Redis"]})],
                "finish_reason": "tool_calls",
            },
            {"content": "说说 Redis 缓存穿透。", "tool_calls": None, "finish_reason": "stop"},
        ]

        with (
            patch("app.agents.chat.nodes.build_react_system_prompt", return_value="prompt"),
            patch("app.services.llm.llm_with_tools", new_callable=AsyncMock, side_effect=llm_responses),
            patch("app.mcp_server.interview_tools._hybrid_search_for_tool", return_value=search_results),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert any(e.get("step") == "force_search_guard" for e in events)
        assert state["tool_steps"][0]["tool_name"] == "search_questions"
        assert state["tool_calls_trace"][0]["tool_name"] == "search_questions"
        assert state["tool_calls_trace"][0]["label"] == "检索题库"
        assert state["tool_calls_trace"][0]["result_count"] == 1
        assert state["tool_calls_trace"][0]["result_preview"][0]["id"] == 101
```

- [ ] **Step 2: Write failing test for load_skill skill_trace**

Append to `backend/tests/chat/test_chat.py`:

```python
class TestRunChatSkillTraceMetadata:
    async def test_load_skill_records_skill_trace_in_done_metadata(self):
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {
                "type": "tool_step",
                "data": {
                    "step": "load_skill",
                    "tool_name": "load_skill",
                    "message": "正在加载项目深挖策略...",
                    "elapsed_ms": 1,
                    "result_count": 0,
                    "fallback_used": False,
                },
            },
            {"type": "chunk", "content": "Answer"},
            {"type": "done", "metadata": {}},
        ]

        async def fake_react_loop(state):
            state["skill_trace"] = [
                {
                    "skill_name": "project-deep-dive",
                    "label": "项目深挖策略",
                    "reason": "候选人正在介绍项目，需要追问职责、架构和取舍",
                    "persistent": False,
                    "status": "loaded",
                }
            ]
            for event in react_events:
                yield event

        with (
            patch("app.agents.chat.pipeline._step_load_context", new_callable=AsyncMock),
            patch("app.agents.chat.pipeline._step_classify", new_callable=AsyncMock),
            patch("app.agents.chat.pipeline._react_loop", side_effect=fake_react_loop),
            patch("app.agents.chat.pipeline._build_react_metadata", return_value=({}, "Answer")),
            patch("app.agents.chat.pipeline._basis_event_payload", return_value={}),
            patch("app.agents.chat.pipeline._persist_active_skills", new_callable=AsyncMock),
            patch("app.agents.chat.pipeline._step_extract_memory", new_callable=AsyncMock),
        ):
            done_event = None
            async for event in run_chat("conv-1", 1, "Hello", mode="free_practice"):
                if event.get("type") == "done":
                    done_event = event

        assert done_event["metadata"]["skill_trace"][0]["skill_name"] == "project-deep-dive"
        assert done_event["metadata"]["skill_trace"][0]["label"] == "项目深挖策略"
```

- [ ] **Step 3: Run tests to verify guard test fails**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_react_loop.py::TestForceSearchGuardTrace -q
```

Expected: FAIL because guard currently does not record `tool_steps` / `tool_calls_trace`.

- [ ] **Step 4: Implement shared record helper in `react_loop.py`**

Import trace helpers:

```python
from app.agents.chat.trace import build_skill_trace_from_tool, build_tool_trace
```

Add helper near tracing functions:

```python
def _record_tool_observability(
    state: ChatState,
    *,
    tool_name: str,
    tool_call: dict,
    summary: dict,
    elapsed_ms: int,
    message: str,
    output: str = "",
) -> dict:
    step_data = {
        "step": tool_name,
        "tool_name": tool_name,
        "message": message,
        "elapsed_ms": elapsed_ms,
        "result_count": summary.get("result_count", 0),
        "fallback_used": summary.get("fallback_used", False),
    }
    state.setdefault("tool_steps", []).append(step_data)
    trace = build_tool_trace(tool_name, tool_call, summary, elapsed_ms, state, output)
    trace["message"] = message
    state.setdefault("tool_calls_trace", []).append(trace)
    skill_trace = build_skill_trace_from_tool(tool_name, tool_call, summary)
    if skill_trace:
        state.setdefault("skill_trace", []).append(skill_trace)
    _emit({"type": "tool_step", "data": step_data})
    return step_data
```

Replace the ordinary tool trace block with:

```python
if tool_name in ("search_questions", "draw_questions", "select_question", "load_skill"):
    _record_tool_observability(
        state,
        tool_name=tool_name,
        tool_call=tc,
        summary=tool_summary,
        elapsed_ms=tool_elapsed_ms,
        message=chat_tools.tool_progress_message(tc),
        output=output,
    )
```

In the `force_search_guard` branch, wrap `chat_tools.execute_tool(gtc, state)` with timing and summary:

```python
gtc_started = time.monotonic()
gtc_output = await chat_tools.execute_tool(gtc, state)
gtc_elapsed_ms = int((time.monotonic() - gtc_started) * 1000)
gtc_summary = _summarize_tool_output(gtc_name, gtc_output, state)
_record_tool_observability(
    state,
    tool_name=gtc_name,
    tool_call=gtc,
    summary=gtc_summary,
    elapsed_ms=gtc_elapsed_ms,
    message=chat_tools.tool_progress_message(gtc),
    output=gtc_output,
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_react_loop.py::TestForceSearchGuardTrace backend/tests/chat/test_chat.py::TestRunChatSkillTraceMetadata -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/chat/react_loop.py backend/tests/chat/test_react_loop.py backend/tests/chat/test_chat.py
git commit -m "feat(chat): trace react tool and skill calls"
```

---

### Task 4: Frontend Reasoning Timeline Details

**Files:**
- Modify: `frontend/src/components/business/ReasoningTimeline.vue`
- Modify: `frontend/src/components/business/ChatMessage.vue`
- Modify: `frontend/src/components/business/ChatView.vue`
- Test: `frontend/tests/e2e/chat-thinking-timer.spec.js`

**Interfaces:**
- Consumes: `reasoningTrace`, `toolCallsTrace`, `skillTrace`, plus legacy `steps`, `toolSteps`, `thinking`, and `duration` props.
- Produces: DS-style title, public summary block, clickable tool details, clickable skill details.
- Preserves: Existing `steps`, `toolSteps`, `content`, `duration`, `isStreaming`, `isSending` props.

- [ ] **Step 1: Add failing E2E test for history tool detail**

Append to `frontend/tests/e2e/chat-thinking-timer.spec.js`:

```javascript
async function mockChatHistoryTrace(page) {
  await page.route('**/api/chat/conversations?status=active', async route => {
    await route.fulfill({
      json: {
        status: 'success',
        data: [{ id: 'conv-trace', title: '模拟面试', mode: 'free_practice', updated_at: new Date().toISOString() }],
      },
    })
  })
  await page.route('**/api/chat/conversations/conv-trace/messages', async route => {
    await route.fulfill({
      json: {
        status: 'success',
        data: [
          {
            id: 1,
            role: 'assistant',
            content: '说说 Redis 缓存穿透。',
            created_at: new Date().toISOString(),
            metadata: {
              reasoning_trace: {
                version: 1,
                duration_ms: 4200,
                source: 'summary_fallback',
                summary: ['分析候选人回答，判断下一步追问方向', '根据关键词检索题库中的相关面试题'],
                model_reasoning: [],
              },
              tool_calls_trace: [
                {
                  tool_name: 'search_questions',
                  label: '检索题库',
                  message: '正在检索相关面试题...',
                  args_summary: { keywords: ['Redis', '缓存'], question_type: 'knowledge_probe' },
                  elapsed_ms: 318,
                  ok: true,
                  result_count: 3,
                  result_ids: [101, 102, 103],
                  result_preview: [{ id: 101, question: 'Redis 缓存穿透怎么处理？', cat1: '中间件', cat2: '缓存' }],
                  selected_question_id: 101,
                  fallback_used: false,
                  empty_reason: '',
                  debug_reason: 'hybrid_search_ok',
                  error: '',
                },
              ],
              skill_trace: [
                {
                  skill_name: 'project-deep-dive',
                  label: '项目深挖策略',
                  reason: '候选人正在介绍项目，需要追问职责、架构和取舍',
                  persistent: false,
                  status: 'loaded',
                },
              ],
            },
          },
        ],
      },
    })
  })
}

test('chat reasoning trace history shows clickable tool and skill details', async ({ page }) => {
  await mockAuthenticatedShell(page)
  await mockChatHistoryTrace(page)

  await page.goto('/chat', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('main')
  await page.getByText('自由练习 · 刚刚').click()

  await expect(page.getByText('已思考 4.2 秒 · 调用 1 个工具 · 加载 1 个策略')).toBeVisible()
  await page.getByText('检索题库 · 318ms · 3 结果').click()
  await expect(page.getByText('工具名 search_questions')).toBeVisible()
  await expect(page.getByText('参数 keywords=Redis, 缓存; question_type=knowledge_probe')).toBeVisible()
  await expect(page.getByText('Redis 缓存穿透怎么处理？')).toBeVisible()
  await page.getByText('项目深挖策略').click()
  await expect(page.getByText('skill project-deep-dive')).toBeVisible()
})
```

- [ ] **Step 2: Run E2E test to verify it fails**

Run:

```bash
cd frontend && npm run test -- chat-thinking-timer.spec.js
```

Expected: FAIL because the new title and clickable details do not exist.

- [ ] **Step 3: Enhance `ReasoningTimeline.vue` props and title**

Add props:

```javascript
reasoningTrace: { type: Object, default: null },
toolCallsTrace: { type: Array, default: () => [] },
skillTrace: { type: Array, default: () => [] },
```

Add helpers:

```javascript
const effectiveDurationMs = computed(() => {
  if (props.reasoningTrace?.duration_ms !== undefined) return Number(props.reasoningTrace.duration_ms) || 0
  return (Number(props.duration) || 0) * 1000
})

const effectiveToolCalls = computed(() => props.toolCallsTrace.length ? props.toolCallsTrace : props.toolSteps.map(step => ({
  label: step.message,
  tool_name: step.tool_name || step.step,
  elapsed_ms: step.elapsed_ms,
  result_count: step.result_count,
  args_summary: {},
  result_preview: [],
})))

const effectiveSkills = computed(() => props.skillTrace)

function formatElapsed(ms) {
  const value = Number(ms) || 0
  if (value >= 1000) return `${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)} 秒`
  return `${value}ms`
}
```

Update `displayLabel`:

```javascript
const displayLabel = computed(() => {
  if (props.isStreaming || (props.isSending && effectiveDurationMs.value > 0 && !props.content)) {
    return `思考中 ${formatElapsed(effectiveDurationMs.value)}`
  }
  if (props.isSending && effectiveDurationMs.value <= 0) return '思考中'
  const parts = []
  if (effectiveDurationMs.value > 0) parts.push(`已思考 ${formatElapsed(effectiveDurationMs.value)}`)
  if (effectiveToolCalls.value.length > 0) parts.push(`调用 ${effectiveToolCalls.value.length} 个工具`)
  if (effectiveSkills.value.length > 0) parts.push(`加载 ${effectiveSkills.value.length} 个策略`)
  if (parts.length === 0 && stepCount.value > 0) parts.push(`${stepCount.value} 步`)
  return parts.length > 0 ? parts.join(' · ') : '思考过程'
})
```

- [ ] **Step 4: Add clickable tool and skill sections**

In template, after steps section and before thinking content, add:

```vue
<div v-if="effectiveSkills.length > 0" class="space-y-1 mb-3">
  <div v-for="(skill, i) in effectiveSkills" :key="skill.skill_name || i" class="group/step">
    <button @click="toggleSkill(i)" class="flex items-center gap-2 w-full text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors">
      <CheckCircle2 :size="12" class="text-emerald-500 shrink-0" />
      <span class="text-muted-foreground flex-1">{{ skill.label || skill.skill_name }}</span>
      <ChevronDown :size="12" class="text-muted-foreground/50 shrink-0 transition-transform duration-200" :class="{ 'rotate-180': expandedSkills[i] }" />
    </button>
    <div v-if="expandedSkills[i]" class="pl-7 pr-2 pb-1 space-y-0.5 text-xs text-muted-foreground/70">
      <p>skill {{ skill.skill_name }}</p>
      <p v-if="skill.reason">{{ skill.reason }}</p>
      <p>状态 {{ skill.status || 'loaded' }}</p>
    </div>
  </div>
</div>

<div v-if="effectiveToolCalls.length > 0" class="space-y-1 mb-3">
  <div v-for="(tool, i) in effectiveToolCalls" :key="`${tool.tool_name || tool.label}-${i}`" class="group/step">
    <button @click="toggleToolCall(i)" class="flex items-center gap-2 w-full text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors">
      <CheckCircle2 v-if="tool.ok !== false" :size="12" class="text-emerald-500 shrink-0" />
      <AlertCircle v-else :size="12" class="text-destructive shrink-0" />
      <span class="text-muted-foreground flex-1">{{ tool.label || tool.message || tool.tool_name }} · {{ formatElapsed(tool.elapsed_ms) }} · {{ tool.result_count ?? 0 }} 结果</span>
      <ChevronDown :size="12" class="text-muted-foreground/50 shrink-0 transition-transform duration-200" :class="{ 'rotate-180': expandedToolCalls[i] }" />
    </button>
    <div v-if="expandedToolCalls[i]" class="pl-7 pr-2 pb-1 space-y-1 text-xs text-muted-foreground/70">
      <p>工具名 {{ tool.tool_name }}</p>
      <p v-if="formatArgs(tool.args_summary)">参数 {{ formatArgs(tool.args_summary) }}</p>
      <p>耗时 {{ formatElapsed(tool.elapsed_ms) }}</p>
      <p>结果 {{ tool.result_count ?? 0 }} 个</p>
      <p v-if="tool.debug_reason">调试 {{ tool.debug_reason }}</p>
      <p v-if="tool.empty_reason">空结果原因 {{ tool.empty_reason }}</p>
      <p v-if="tool.error" class="text-destructive">错误 {{ tool.error }}</p>
      <div v-if="tool.result_preview?.length" class="space-y-1">
        <div v-for="q in tool.result_preview" :key="q.id || q.question" class="rounded-md border border-border/50 bg-muted/30 px-2 py-1">
          <span v-if="q.id">#{{ q.id }} </span>{{ q.question }}
        </div>
      </div>
    </div>
  </div>
</div>
```

Add script state and helpers:

```javascript
import { Loader2, Lightbulb, ChevronDown, CheckCircle2, AlertCircle } from '@lucide/vue'

const expandedSkills = reactive({})
const expandedToolCalls = reactive({})

function toggleSkill(index) {
  expandedSkills[index] = !expandedSkills[index]
}

function toggleToolCall(index) {
  expandedToolCalls[index] = !expandedToolCalls[index]
}

function formatArgs(args) {
  if (!args || typeof args !== 'object') return ''
  return Object.entries(args)
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(', ') : value}`)
    .join('; ')
}
```

- [ ] **Step 5: Normalize metadata in `ChatMessage.vue`**

Add computed values:

```javascript
const reasoningTrace = computed(() => props.message.metadata?.reasoning_trace || null)
const toolCallsTrace = computed(() => props.message.metadata?.tool_calls_trace || [])
const skillTrace = computed(() => props.message.metadata?.skill_trace || [])
```

Pass them to `ReasoningTimeline`:

```vue
:reasoning-trace="reasoningTrace"
:tool-calls-trace="toolCallsTrace"
:skill-trace="skillTrace"
```

Update the `v-if` to include new fields:

```vue
v-if="timelineSteps.length || timelineToolSteps.length || message.metadata?.thinking || reasoningTrace || toolCallsTrace.length || skillTrace.length"
```

- [ ] **Step 6: Keep live metadata compatible in `ChatView.vue`**

When building the final assistant `metadata`, add a minimal client-side fallback only if backend did not send new fields:

```javascript
if (!metadata.reasoning_trace) {
  metadata.reasoning_trace = {
    version: 1,
    duration_ms: Math.round((thinkingDuration.value || liveThinkingSeconds.value || 0) * 1000),
    source: thinkingContent.value ? 'model_reasoning' : 'summary_fallback',
    summary: processingSteps.value.map(s => s.message).filter(Boolean).slice(0, 8),
    model_reasoning: thinkingContent.value ? [{ chunks: [thinkingContent.value], duration_ms: Math.round((thinkingDuration.value || 0) * 1000), truncated: false }] : [],
  }
}
if (!metadata.tool_calls_trace && pendingToolSteps.value.length > 0) {
  metadata.tool_calls_trace = pendingToolSteps.value.map(step => ({
    tool_name: step.tool_name || step.step,
    label: step.message || step.tool_name || step.step,
    message: step.message || '',
    args_summary: {},
    elapsed_ms: step.elapsed_ms || 0,
    ok: true,
    result_count: step.result_count || 0,
    result_ids: [],
    result_preview: [],
    selected_question_id: pendingSelectedQuestion.value?.id || null,
    fallback_used: !!step.fallback_used,
    empty_reason: '',
    debug_reason: '',
    error: '',
  }))
}
if (!metadata.skill_trace && processingSteps.value.some(step => step.step === 'load_skill')) {
  metadata.skill_trace = processingSteps.value
    .filter(step => step.step === 'load_skill')
    .map(step => ({
      skill_name: step.skill_name || '',
      label: step.message || step.skill_name || '面试策略',
      reason: step.reason || '',
      persistent: false,
      status: 'loaded',
    }))
}
```

- [ ] **Step 7: Run E2E and build**

Run:

```bash
cd frontend && npm run test -- chat-thinking-timer.spec.js
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/business/ReasoningTimeline.vue frontend/src/components/business/ChatMessage.vue frontend/src/components/business/ChatView.vue frontend/tests/e2e/chat-thinking-timer.spec.js
git commit -m "feat(frontend): show chat reasoning trace details"
```

---

### Task 5: Documentation, Focused Regression, And Final Verification

**Files:**
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Modify: `frontend/src/components/business/CLAUDE.md`

**Interfaces:**
- Consumes: The final backend and frontend behavior from Tasks 1-4.
- Produces: Updated local manuals and final verification evidence.

- [ ] **Step 1: Update backend manual**

In `backend/app/agents/chat/CLAUDE.md`, replace the existing Thinking/Steps bullet with:

```markdown
- **Reasoning Trace 持久化**：`run_chat()` 在 done metadata 中保存新字段 `reasoning_trace`、`tool_calls_trace`、`skill_trace`，并继续写旧字段 `thinking`、`thinking_duration`、`steps`、`tool_steps`、`insights`。前端展示的是模型显式 reasoning 或后端公开摘要，不展示隐藏原始 CoT。普通 ReAct 工具路径和 `force_search_guard` 路径必须共用 trace 记录，工具参数和结果只保存 allowlist 摘要。
```

- [ ] **Step 2: Update frontend manual**

In `frontend/src/components/business/CLAUDE.md`, update component rows:

```markdown
| `ChatMessage.vue` | Chat 消息气泡（Markdown 渲染）；从历史 metadata 恢复 `reasoning_trace`、`tool_calls_trace`、`skill_trace`，并兼容旧 thinking/step/tool_steps 字段 |
| `ChatView.vue` | Chat 主视图（SSE 流式）；新建面试支持 difficulty 和面经节奏来源，流式期间保留 step/tool_step/thinking 并补齐 reasoning trace 兼容 metadata |
| `ReasoningTimeline.vue` | DS 风格 AI 思考与执行轨迹面板；展示公开思考摘要、模型显式 reasoning、可点击工具调用详情和 skill 加载详情 |
```

- [ ] **Step 3: Run focused backend chat tests**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_chat.py::TestReasoningTraceHelpers backend/tests/chat/test_chat.py::TestRunChatReasoningTraceMetadata backend/tests/chat/test_chat.py::TestRunChatSkillTraceMetadata backend/tests/chat/test_react_loop.py::TestForceSearchGuardTrace -q
```

Expected: PASS.

- [ ] **Step 4: Run broader chat backend tests**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/ -q
```

Expected: PASS, unless unrelated existing dirty-worktree tests fail. If unrelated failures occur, capture exact failing tests and error lines.

- [ ] **Step 5: Run frontend verification**

Run:

```bash
cd frontend && npm run test -- chat-thinking-timer.spec.js
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit docs and any final fixes**

```bash
git add backend/app/agents/chat/CLAUDE.md frontend/src/components/business/CLAUDE.md
git commit -m "docs(chat): document reasoning trace contract"
```

If final fixes were needed in production code, include them with the docs commit only when they are directly tied to the verification failures.

---

## Self-Review

### Spec Coverage

- DS-style panel: Task 4 updates `ReasoningTimeline.vue`.
- Clickable tool details: Task 4 adds clickable tool sections and E2E.
- Skill visibility: Task 1 defines skill trace, Task 3 records it, Task 4 renders it.
- Backend persistence for E2E and real usage: Tasks 2 and 3 merge traces into `done.metadata`, which the route already persists.
- `force_search_guard` trace bug: Task 3 directly tests and fixes it.
- Legacy compatibility: Tasks 2 and 4 keep old metadata fields and frontend fallbacks.
- Safety boundary: Task 1 allowlists args and previews only public question fields; Task 4 labels the content as public reasoning summary.

### Placeholder Scan

This plan contains no unresolved blanks. Every task names files, functions, tests, commands, and expected outcomes.

### Type Consistency

- Backend trace functions consistently use `dict` / `list[dict]` and return JSON-serializable metadata.
- Frontend props use `reasoningTrace`, `toolCallsTrace`, `skillTrace`, matching kebab-case bindings `reasoning-trace`, `tool-calls-trace`, `skill-trace`.
- Duration fields use milliseconds in new metadata and are formatted in `ReasoningTimeline.vue`.

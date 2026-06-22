# Chat Tools Gateway Question Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden chat tool execution with a typed Tool Gateway, then bind new-question turns to a locally selected `selected_question` plan with adherence repair.

**Architecture:** Add a focused gateway module beside the existing chat tools to validate tool inputs, normalize outputs, and keep legacy state/SSE compatibility. Then add small pipeline helpers that create a `next_question_plan` only for new-question scenarios, inject it before final generation, verify adherence after generation, and repair once if needed.

**Tech Stack:** Python 3, FastAPI backend, Pydantic v2, pytest, existing ReAct chat pipeline, SQLite-backed services. All Python tests must run through Docker with `docker compose exec backend uv run pytest ...`.

---

## Scope and sequencing

This plan implements the accepted spec in two independently testable slices:

1. **Gateway slice:** typed envelopes for `search_questions` and `draw_questions`, with validation, metrics, normalized items, errors, and legacy state compatibility.
2. **Question-plan slice:** selected-question plan creation, plan injection, adherence checking, repair/fallback, and metadata priority.

Do not start slice 2 until slice 1 tests pass and are committed.

## File structure

### Create

- `backend/app/agents/chat/tool_gateway.py`
  - Owns Pydantic models for tool inputs/outputs.
  - Owns result normalization and small error/envelope helpers.
  - Does not call LLM.
  - Does not emit SSE.

### Modify

- `backend/app/agents/chat/tools.py`
  - Use gateway models in `_execute_search_questions()` and `_execute_draw_questions()`.
  - Return compact tool envelope JSON instead of bare list for search/draw.
  - Preserve `state["retrieved_questions"]`, `state["candidate_questions"]`, `state["question_source"]`, and `state["question_source_reason"]`.

- `backend/app/agents/chat/pipeline.py`
  - Teach tool-output summarization to understand envelopes.
  - When appending tool result messages, prune envelope `items` to top 3.
  - Add question-plan helper functions.
  - Inject `next_question_plan` into final generation messages.
  - Run adherence/repair before emitting final chunks.
  - Prefer plan-selected question in metadata.

- `backend/app/agents/chat/state.py`
  - Add optional typed-dict fields for `tool_results`, `next_question_plan`, and `question_plan_metadata` if this file currently enumerates state fields. If it is loose, keep runtime state only and do not over-edit.

- `backend/app/agents/chat/CLAUDE.md`
  - Document Tool Gateway, envelope, and question plan protection.

- `backend/app/services/CLAUDE.md`
  - Only update if `fts_service.py` or `question_draw_service.py` signatures change. This implementation should avoid service signature changes, so no edit is expected.

- `backend/tests/chat/test_tools.py`
  - Add gateway envelope tests and update existing search/draw tests from bare list expectations to envelope expectations.

- `backend/tests/chat/test_react_loop.py`
  - Add envelope compatibility and question-plan tests.

- `docs/dev-log/YYYY-MM-DD-chat-tools-gateway-question-plan.md`
  - Record implementation summary and test commands.

### Avoid modifying

- `frontend/` files.
- API router files.
- Database migrations.
- `README.md`, unless implementation unexpectedly adds external API, dependency, environment variable, or deployment behavior.

---

## Task 1: Add Tool Gateway models and normalization helpers

**Files:**
- Create: `backend/app/agents/chat/tool_gateway.py`
- Test: `backend/tests/chat/test_tools.py`

- [ ] **Step 1: Add failing tests for envelope model behavior**

Append these tests to `backend/tests/chat/test_tools.py` after existing schema tests or before `TestExecuteToolSearchQuestions`:

```python
class TestToolGatewayModels:
    def test_normalize_search_question_item_prefers_combined_score(self):
        from app.agents.chat.tool_gateway import normalize_question_item

        item = normalize_question_item(
            {
                "id": 42,
                "question": "介绍一下 RAG 的检索和重排流程",
                "cat1": "B.Agent与LLM应用",
                "cat2": "B2.RAG系统设计",
                "tags": "rag,检索,重排",
                "_combined_rank_score": 0.123456,
                "_rrf_score": 0.05,
                "sources": "[{\"company\": \"测试公司\", \"round\": \"一面\"}]",
            },
            source="search",
            reason="rrf_ranked",
        )

        assert item["id"] == 42
        assert item["question"] == "介绍一下 RAG 的检索和重排流程"
        assert item["cat1"] == "B.Agent与LLM应用"
        assert item["cat2"] == "B2.RAG系统设计"
        assert item["source"] == "search"
        assert item["score"] == 0.123456
        assert item["reason"] == "rrf_ranked"
        assert item["sources"] == [{"company": "测试公司", "round": "一面"}]

    def test_build_tool_success_envelope_has_stable_shape(self):
        from app.agents.chat.tool_gateway import build_success_envelope

        envelope = build_success_envelope(
            tool="search_questions",
            items=[
                {
                    "id": 1,
                    "question": "What is JVM?",
                    "cat1": "Java",
                    "cat2": "Basics",
                    "source": "search",
                    "score": 0.1,
                    "reason": "rrf_ranked",
                    "tags": "jvm",
                    "difficulty": "medium",
                    "sources": [],
                }
            ],
            total_ms=7,
            debug_reason="hybrid_search_ok",
        )

        assert envelope["ok"] is True
        assert envelope["tool"] == "search_questions"
        assert envelope["items"][0]["id"] == 1
        assert envelope["metadata"]["result_count"] == 1
        assert envelope["metadata"]["fallback_used"] is False
        assert envelope["metadata"]["metrics"]["total_ms"] == 7
        assert envelope["metadata"]["debug_reason"] == "hybrid_search_ok"
        assert envelope["error"] is None

    def test_build_tool_error_envelope_has_error_code(self):
        from app.agents.chat.tool_gateway import build_error_envelope

        envelope = build_error_envelope(
            tool="draw_questions",
            error_code="USER_REQUIRED",
            message="user_id is required for draw_questions",
            total_ms=2,
            debug_reason="missing_user_id",
        )

        assert envelope["ok"] is False
        assert envelope["tool"] == "draw_questions"
        assert envelope["items"] == []
        assert envelope["metadata"]["result_count"] == 0
        assert envelope["metadata"]["metrics"]["total_ms"] == 2
        assert envelope["metadata"]["debug_reason"] == "missing_user_id"
        assert envelope["error"] == {
            "error_code": "USER_REQUIRED",
            "message": "user_id is required for draw_questions",
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_tools.py::TestToolGatewayModels -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.chat.tool_gateway'`.

- [ ] **Step 3: Implement minimal gateway models and helpers**

Create `backend/app/agents/chat/tool_gateway.py`:

```python
"""Typed gateway helpers for chat ReAct tools.

This module keeps LLM-facing tool execution predictable: validate inputs,
normalize question rows, and return one stable envelope shape.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ToolName = Literal["search_questions", "draw_questions"]
QuestionSource = Literal["search", "draw"]


class ToolMetrics(BaseModel):
    """Best-effort tool timing metrics in milliseconds."""

    total_ms: int = 0
    fts_ms: int | None = None
    cjk_like_ms: int | None = None
    vector_ms: int | None = None
    rerank_ms: int | None = None
    db_ms: int | None = None


class ToolError(BaseModel):
    error_code: str
    message: str


class ToolQuestionItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int = Field(gt=0)
    question: str = Field(min_length=1)
    cat1: str = ""
    cat2: str = ""
    source: QuestionSource
    score: float | None = None
    reason: str
    tags: str = ""
    difficulty: str = ""
    sources: list[dict] = Field(default_factory=list)


class ToolMetadata(BaseModel):
    result_count: int = 0
    fallback_used: bool = False
    fallback_steps: list[str] = Field(default_factory=list)
    empty_reason: str | None = None
    debug_reason: str = ""
    metrics: ToolMetrics = Field(default_factory=ToolMetrics)


class ToolEnvelope(BaseModel):
    ok: bool
    tool: ToolName
    items: list[ToolQuestionItem] = Field(default_factory=list)
    metadata: ToolMetadata = Field(default_factory=ToolMetadata)
    error: ToolError | None = None


class SearchQuestionsInput(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=5)
    question_type: Literal["project_followup", "knowledge_probe", "new_question"] | None = None
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("keywords", mode="before")
    @classmethod
    def clean_keywords(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("keywords must be a list of strings")
        cleaned = []
        for item in value:
            text = str(item or "").strip()
            if text:
                cleaned.append(text[:80])
        return cleaned[:5]


class DrawQuestionsInput(BaseModel):
    count: int = Field(default=3, ge=1, le=5)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    cat1: str | None = Field(default=None, max_length=80)
    cat2: str | None = Field(default=None, max_length=80)
    topic: str | None = Field(default=None, max_length=80)
    question_type: Literal[
        "algorithm_coding",
        "project_followup",
        "knowledge_probe",
        "system_design",
        "hr",
    ] | None = None

    @field_validator("cat1", "cat2", "topic", mode="before")
    @classmethod
    def clean_optional_text(cls, value: object) -> str | None:
        text = str(value or "").strip()
        return text[:80] if text else None


def _parse_sources(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _extract_score(raw: dict) -> float | None:
    for key in ("_combined_rank_score", "_rrf_score", "score", "rank"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def normalize_question_item(
    raw: dict,
    *,
    source: QuestionSource,
    reason: str,
) -> dict:
    """Normalize a service row into a stable tool question item dict."""

    item = ToolQuestionItem(
        id=int(raw.get("id")),
        question=str(raw.get("question") or "").strip(),
        cat1=str(raw.get("cat1") or ""),
        cat2=str(raw.get("cat2") or ""),
        source=source,
        score=_extract_score(raw),
        reason=reason,
        tags=str(raw.get("tags") or ""),
        difficulty=str(raw.get("difficulty") or ""),
        sources=_parse_sources(raw.get("sources")),
    )
    return item.model_dump()


def build_success_envelope(
    *,
    tool: ToolName,
    items: list[dict],
    total_ms: int,
    debug_reason: str,
    fallback_used: bool = False,
    fallback_steps: list[str] | None = None,
    empty_reason: str | None = None,
) -> dict:
    envelope = ToolEnvelope(
        ok=True,
        tool=tool,
        items=items,
        metadata=ToolMetadata(
            result_count=len(items),
            fallback_used=fallback_used,
            fallback_steps=fallback_steps or [],
            empty_reason=empty_reason,
            debug_reason=debug_reason,
            metrics=ToolMetrics(total_ms=max(0, int(total_ms))),
        ),
        error=None,
    )
    return envelope.model_dump()


def build_error_envelope(
    *,
    tool: ToolName,
    error_code: str,
    message: str,
    total_ms: int,
    debug_reason: str,
    empty_reason: str | None = None,
) -> dict:
    envelope = ToolEnvelope(
        ok=False,
        tool=tool,
        items=[],
        metadata=ToolMetadata(
            result_count=0,
            empty_reason=empty_reason,
            debug_reason=debug_reason,
            metrics=ToolMetrics(total_ms=max(0, int(total_ms))),
        ),
        error=ToolError(error_code=error_code, message=message),
    )
    return envelope.model_dump()
```

- [ ] **Step 4: Run model tests to verify they pass**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_tools.py::TestToolGatewayModels -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/app/agents/chat/tool_gateway.py backend/tests/chat/test_tools.py
git commit -m "feat(backend): add chat tool gateway models"
```

---

## Task 2: Route search_questions and draw_questions through the gateway

**Files:**
- Modify: `backend/app/agents/chat/tools.py`
- Test: `backend/tests/chat/test_tools.py`

- [ ] **Step 1: Replace existing bare-list assertions with envelope assertions**

In `backend/tests/chat/test_tools.py`, update `TestExecuteToolSearchQuestions.test_search_returns_json_results` body assertions after `parsed = json.loads(result)` to:

```python
        assert parsed["ok"] is True
        assert parsed["tool"] == "search_questions"
        assert len(parsed["items"]) == 4
        assert parsed["items"][0]["id"] == 1
        assert parsed["items"][0]["source"] == "search"
        assert parsed["metadata"]["result_count"] == 4
        assert parsed["metadata"]["metrics"]["total_ms"] >= 0
        assert parsed["error"] is None
        assert sample_state["retrieved_questions"] == mock_results
        assert sample_state["candidate_questions"] == mock_results
        assert sample_state["question_source"] == "search"
```

Update `TestExecuteToolDrawQuestions.test_draw_returns_json_results` assertions after `parsed = json.loads(result)` to:

```python
        assert parsed["ok"] is True
        assert parsed["tool"] == "draw_questions"
        assert len(parsed["items"]) == 2
        assert parsed["items"][0]["id"] == 10
        assert parsed["items"][0]["source"] == "draw"
        assert parsed["metadata"]["result_count"] == 2
        assert parsed["metadata"]["metrics"]["total_ms"] >= 0
        assert parsed["error"] is None
        assert sample_state["retrieved_questions"] == mock_results
        assert sample_state["candidate_questions"] == mock_results
        assert sample_state["question_source"] == "draw"
```

- [ ] **Step 2: Add gateway error tests**

Append to `TestExecuteToolSearchQuestions`:

```python
    async def test_search_empty_keywords_returns_no_query_envelope(self, sample_state):
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": []}),
            }
        }

        result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "search_questions"
        assert parsed["items"] == []
        assert parsed["error"]["error_code"] == "NO_QUERY"
        assert parsed["metadata"]["empty_reason"] == "no_query"
        assert sample_state.get("retrieved_questions") == []

    async def test_search_service_error_returns_service_error_envelope(self, sample_state):
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": ["RAG"]}),
            }
        }

        with patch("app.agents.chat.tools._hybrid_search", side_effect=RuntimeError("db down")):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "search_questions"
        assert parsed["error"]["error_code"] == "SERVICE_ERROR"
        assert parsed["metadata"]["empty_reason"] == "service_unavailable"
        assert "db down" not in parsed["error"]["message"]
```

Append to `TestExecuteToolDrawQuestions`:

```python
    async def test_draw_missing_user_returns_user_required_envelope(self):
        from app.agents.chat.tools import execute_tool

        state = {"retrieved_questions": []}
        tool_call = {
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({"count": 1}),
            }
        }

        result = await execute_tool(tool_call, state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "draw_questions"
        assert parsed["error"]["error_code"] == "USER_REQUIRED"
        assert parsed["metadata"]["debug_reason"] == "missing_user_id"

    async def test_draw_invalid_count_returns_validation_error_envelope(self, sample_state):
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({"count": 99}),
            }
        }

        result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert parsed["tool"] == "draw_questions"
        assert parsed["error"]["error_code"] == "VALIDATION_ERROR"
        assert parsed["metadata"]["debug_reason"] == "validation_failed"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_tools.py -q
```

Expected: FAIL because `execute_tool()` still returns bare lists for search/draw and old errors.

- [ ] **Step 4: Implement gateway execution in `tools.py`**

In `backend/app/agents/chat/tools.py`, add imports near the top:

```python
import time
from pydantic import ValidationError
from app.agents.chat.tool_gateway import (
    DrawQuestionsInput,
    SearchQuestionsInput,
    build_error_envelope,
    build_success_envelope,
    normalize_question_item,
)
```

Replace `_execute_search_questions()` with:

```python
async def _execute_search_questions(args: dict, state: ChatState) -> str:
    """Search questions via hybrid_search, update state, return a tool envelope."""
    started = time.monotonic()
    try:
        parsed_args = SearchQuestionsInput(**args)
    except ValidationError:
        total_ms = int((time.monotonic() - started) * 1000)
        return json.dumps(
            build_error_envelope(
                tool="search_questions",
                error_code="VALIDATION_ERROR",
                message="Invalid search_questions arguments",
                total_ms=total_ms,
                debug_reason="validation_failed",
            ),
            ensure_ascii=False,
        )

    if not parsed_args.keywords and not state.get("search_query"):
        total_ms = int((time.monotonic() - started) * 1000)
        state["candidate_questions"] = []
        state["retrieved_questions"] = []
        state["question_source"] = "search"
        state["question_source_reason"] = "search_questions_no_query"
        return json.dumps(
            build_error_envelope(
                tool="search_questions",
                error_code="NO_QUERY",
                message="search_questions requires keywords or search_query",
                total_ms=total_ms,
                debug_reason="no_query",
                empty_reason="no_query",
            ),
            ensure_ascii=False,
        )

    search_args: dict[str, object] = {"keywords": parsed_args.keywords}
    if state.get("search_query"):
        search_args["query_text"] = state["search_query"]
    if parsed_args.question_type:
        search_args["question_type"] = parsed_args.question_type
    if state.get("question_type") and "question_type" not in search_args:
        search_args["question_type"] = state["question_type"]
    if state.get("job_position"):
        search_args["job_position"] = state["job_position"]
    if state.get("retrieval_intent"):
        search_args["retrieval_intent"] = state["retrieval_intent"]
    if state.get("search_negative_terms"):
        search_args["negative_terms"] = state["search_negative_terms"]
    if state.get("retrieved_questions"):
        exclude_ids = {
            q.get("id")
            for q in state["retrieved_questions"]
            if isinstance(q, dict) and q.get("id")
        }
        if exclude_ids:
            search_args["exclude_ids"] = exclude_ids

    try:
        results = await asyncio.to_thread(_hybrid_search, **search_args)
    except Exception:
        logger.exception("search_questions service failed")
        total_ms = int((time.monotonic() - started) * 1000)
        return json.dumps(
            build_error_envelope(
                tool="search_questions",
                error_code="SERVICE_ERROR",
                message="search_questions service failed",
                total_ms=total_ms,
                debug_reason="service_error",
                empty_reason="service_unavailable",
            ),
            ensure_ascii=False,
        )

    state["candidate_questions"] = results
    state["retrieved_questions"] = results
    state["question_source"] = "search"
    state["question_source_reason"] = "search_questions returned candidate questions"

    items = [
        normalize_question_item(item, source="search", reason="rrf_ranked")
        for item in results
        if isinstance(item, dict) and item.get("id") and item.get("question")
    ]
    total_ms = int((time.monotonic() - started) * 1000)
    envelope = build_success_envelope(
        tool="search_questions",
        items=items,
        total_ms=total_ms,
        debug_reason="hybrid_search_ok" if items else "no_match",
        empty_reason=None if items else "no_match",
    )
    return json.dumps(envelope, ensure_ascii=False)
```

Replace `_execute_draw_questions()` with:

```python
async def _execute_draw_questions(args: dict, state: ChatState) -> str:
    """Draw random questions, update state, return a tool envelope."""
    started = time.monotonic()
    try:
        parsed_args = DrawQuestionsInput(**args)
    except ValidationError:
        total_ms = int((time.monotonic() - started) * 1000)
        return json.dumps(
            build_error_envelope(
                tool="draw_questions",
                error_code="VALIDATION_ERROR",
                message="Invalid draw_questions arguments",
                total_ms=total_ms,
                debug_reason="validation_failed",
            ),
            ensure_ascii=False,
        )

    user_id = state.get("user_id")
    if not user_id:
        total_ms = int((time.monotonic() - started) * 1000)
        return json.dumps(
            build_error_envelope(
                tool="draw_questions",
                error_code="USER_REQUIRED",
                message="user_id is required for draw_questions",
                total_ms=total_ms,
                debug_reason="missing_user_id",
            ),
            ensure_ascii=False,
        )

    draw_args: dict[str, object] = {
        "user": {
            "id": user_id,
            "bank_mode": state.get("bank_mode", "public"),
        },
        "count": parsed_args.count,
    }
    for key in ("difficulty", "cat1", "cat2", "topic", "question_type"):
        value = getattr(parsed_args, key)
        if value:
            draw_args[key] = value
    if state.get("retrieved_questions"):
        exclude_ids = {
            q.get("id")
            for q in state["retrieved_questions"]
            if isinstance(q, dict) and q.get("id")
        }
        if exclude_ids:
            draw_args["exclude_ids"] = exclude_ids

    try:
        results = await asyncio.to_thread(_draw_questions, **draw_args)
    except Exception:
        logger.exception("draw_questions service failed")
        total_ms = int((time.monotonic() - started) * 1000)
        return json.dumps(
            build_error_envelope(
                tool="draw_questions",
                error_code="SERVICE_ERROR",
                message="draw_questions service failed",
                total_ms=total_ms,
                debug_reason="service_error",
                empty_reason="service_unavailable",
            ),
            ensure_ascii=False,
        )

    state["candidate_questions"] = results
    state["retrieved_questions"] = results
    state["question_source"] = "draw"
    state["question_source_reason"] = "draw_questions returned candidate questions"

    items = [
        normalize_question_item(item, source="draw", reason="weighted_draw")
        for item in results
        if isinstance(item, dict) and item.get("id") and item.get("question")
    ]
    total_ms = int((time.monotonic() - started) * 1000)
    envelope = build_success_envelope(
        tool="draw_questions",
        items=items,
        total_ms=total_ms,
        debug_reason="weighted_draw_ok" if items else "no_match",
        empty_reason=None if items else "no_match",
    )
    return json.dumps(envelope, ensure_ascii=False)
```

- [ ] **Step 5: Run tool tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_tools.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add backend/app/agents/chat/tools.py backend/tests/chat/test_tools.py
git commit -m "feat(backend): return structured chat tool envelopes"
```

---

## Task 3: Make ReAct loop compatible with tool envelopes

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: Add failing ReAct envelope compatibility test**

Append this test to `TestReactLoop` in `backend/tests/chat/test_react_loop.py`:

```python
    async def test_tool_envelope_emits_retrieved_and_prunes_message_output(self):
        """ReAct should understand structured tool envelopes and keep LLM messages compact."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "给我一道 RAG 题",
            "model": None,
            "intent": "practice_request",
            "answer_complete": False,
        }
        tc_search = _tc("search_questions", {"keywords": ["RAG"]})
        captured_messages = []

        async def mock_llm(messages, *args, **kwargs):
            captured_messages.append(messages)
            if len(captured_messages) == 1:
                return {
                    "content": None,
                    "tool_calls": [tc_search],
                    "finish_reason": "tool_calls",
                }
            return {
                "content": "请你说说 RAG 的检索和重排怎么设计？",
                "tool_calls": None,
                "finish_reason": "stop",
            }

        envelope = {
            "ok": True,
            "tool": "search_questions",
            "items": [
                {"id": i, "question": f"RAG question {i}", "cat1": "B", "cat2": "RAG", "source": "search", "score": 0.1, "reason": "rrf_ranked", "sources": []}
                for i in range(1, 6)
            ],
            "metadata": {"result_count": 5, "fallback_used": False, "fallback_steps": [], "empty_reason": None, "debug_reason": "hybrid_search_ok", "metrics": {"total_ms": 5}},
            "error": None,
        }

        async def mock_execute_tool(tc, st):
            st["retrieved_questions"] = [
                {"id": i, "question": f"RAG question {i}", "cat1": "B", "cat2": "RAG", "sources": []}
                for i in range(1, 6)
            ]
            st["candidate_questions"] = st["retrieved_questions"]
            st["question_source"] = "search"
            return json.dumps(envelope, ensure_ascii=False)

        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch("app.agents.chat.pipeline.build_react_system_prompt", return_value="Prompt."),
                patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm),
                patch("app.agents.chat.pipeline.execute_tool", side_effect=mock_execute_tool),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        retrieved = next(e for e in emitted if e.get("type") == "retrieved")
        assert [q["id"] for q in retrieved["questions"]] == [1, 2, 3]

        second_messages = captured_messages[1]
        tool_messages = [m for m in second_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        tool_payload = json.loads(tool_messages[0]["content"])
        assert tool_payload["ok"] is True
        assert len(tool_payload["items"]) == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestReactLoop::test_tool_envelope_emits_retrieved_and_prunes_message_output -q
```

Expected: FAIL because `_react_loop()` only prunes bare list outputs.

- [ ] **Step 3: Update `_summarize_tool_output()` and pruning logic**

In `backend/app/agents/chat/pipeline.py`, replace the search/draw block inside `_summarize_tool_output()` with logic that recognizes envelopes:

```python
    if tool_name in {"search_questions", "draw_questions"}:
        if isinstance(parsed, dict) and "ok" in parsed and "items" in parsed:
            summary["ok"] = bool(parsed.get("ok"))
            if not summary["ok"] and parsed.get("error"):
                error = parsed.get("error") or {}
                summary["error"] = str(error.get("error_code") or "tool_error")[:_TRACE_STRING_LIMIT]
            items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
            summary["result_count"] = len(items)
            summary["result_ids"] = [
                q.get("id")
                for q in items[:_TRACE_LIST_LIMIT]
                if isinstance(q, dict) and q.get("id") is not None
            ]
            metadata = parsed.get("metadata") or {}
            summary["fallback_used"] = bool(metadata.get("fallback_used", False))
            summary["empty_reason"] = metadata.get("empty_reason")
            return summary

        results = (
            [] if not summary["ok"] else state.get("retrieved_questions", []) or []
        )
        summary["result_count"] = len(results)
        summary["result_ids"] = [
            q.get("id")
            for q in results[:_TRACE_LIST_LIMIT]
            if isinstance(q, dict) and q.get("id") is not None
        ]
        return summary
```

In `_react_loop()`, replace the `# 3d: Pre-prune search/draw tool output` block with:

```python
            msg_output = output
            if tool_name in ("search_questions", "draw_questions"):
                try:
                    parsed_out = json.loads(output)
                    if isinstance(parsed_out, dict) and isinstance(parsed_out.get("items"), list):
                        parsed_out = {**parsed_out, "items": parsed_out["items"][:3]}
                        msg_output = json.dumps(parsed_out, ensure_ascii=False)
                    elif isinstance(parsed_out, list) and len(parsed_out) > 3:
                        msg_output = json.dumps(parsed_out[:3], ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass
```

- [ ] **Step 4: Run ReAct compatibility test**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestReactLoop::test_tool_envelope_emits_retrieved_and_prunes_message_output -q
```

Expected: PASS.

- [ ] **Step 5: Run chat tests impacted so far**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_tools.py backend/tests/chat/test_react_loop.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add backend/app/agents/chat/pipeline.py backend/tests/chat/test_react_loop.py
git commit -m "fix(backend): support structured tool envelopes in react loop"
```

---

## Task 4: Add question-plan selection helpers

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: Add failing unit tests for plan trigger and selection**

Append a new class near other pipeline helper tests in `backend/tests/chat/test_react_loop.py`:

```python
class TestQuestionPlanHelpers:
    def test_should_create_question_plan_for_practice_request(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        state = {"intent": "practice_request", "answer_complete": False}
        assert _should_create_question_plan(state) is True

    def test_should_create_question_plan_for_complete_interview_answer(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        state = {"intent": "interview_question", "answer_complete": True}
        assert _should_create_question_plan(state) is True

    def test_should_not_create_question_plan_for_follow_up_chat_or_end(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        assert _should_create_question_plan({"intent": "follow_up", "answer_complete": False}) is False
        assert _should_create_question_plan({"intent": "chat", "answer_complete": False}) is False
        assert _should_create_question_plan({"intent": "end_interview", "answer_complete": False}) is False
        assert _should_create_question_plan({"intent": "interview_question", "answer_complete": False}) is False

    def test_select_question_for_plan_prefers_algorithm_candidate(self):
        from app.agents.chat.pipeline import _select_question_for_plan

        state = {"question_type": "algorithm_coding", "search_negative_terms": []}
        candidates = [
            {"id": 1, "question": "说说 Redis 持久化", "cat1": "后端", "cat2": "Redis", "tags": "redis"},
            {"id": 2, "question": "实现 LRU Cache", "cat1": "E.算法与数据结构", "cat2": "E2.算法手撕", "tags": "代码,lru"},
        ]

        selected, reason = _select_question_for_plan(state, candidates)

        assert selected["id"] == 2
        assert reason == "algorithm_candidate_match"

    def test_build_question_plan_sets_state_selected_question(self):
        from app.agents.chat.pipeline import _maybe_create_question_plan

        state = {
            "intent": "practice_request",
            "answer_complete": False,
            "question_source": "search",
            "search_negative_terms": ["HR"],
        }
        candidates = [
            {"id": 7, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "tags": "检索,重排"}
        ]
        state["candidate_questions"] = candidates

        plan = _maybe_create_question_plan(state)

        assert plan["must_ask"] is True
        assert plan["question_id"] == 7
        assert plan["question_text"] == "RAG 检索怎么设计？"
        assert plan["source"] == "search"
        assert "RAG" in plan["allowed_focus"]
        assert state["selected_question"]["id"] == 7
        assert state["next_question_plan"]["question_id"] == 7
        assert state["question_source_reason"] == "question_plan_bound"
```

- [ ] **Step 2: Run helper tests to verify they fail**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestQuestionPlanHelpers -q
```

Expected: FAIL with missing helper imports.

- [ ] **Step 3: Implement helper functions in `pipeline.py`**

Add these helpers near existing selected-question helpers in `backend/app/agents/chat/pipeline.py`, after `_infer_selected_question()`:

```python
def _should_create_question_plan(state: ChatState) -> bool:
    """Return True when this turn is expected to ask a new bank-backed question."""
    intent = state.get("intent")
    if intent == "practice_request":
        return True
    if intent == "interview_question" and state.get("answer_complete") is True:
        return True
    if state.get("question_type") == "algorithm_coding":
        return True
    user_message = str(state.get("user_message") or "")
    return bool(re.search(r"(出题|来一道|换题|随机|手撕|代码题)", user_message))


def _candidate_contains_negative_term(candidate: dict, negative_terms: list[str]) -> bool:
    if not negative_terms:
        return False
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    ).lower()
    return any(str(term or "").lower() in text for term in negative_terms if term)


def _is_algorithm_candidate(candidate: dict) -> bool:
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    )
    return bool(re.search(r"(算法|代码|手撕|数据结构|链表|排序|二分|LRU|lru)", text, re.I))


def _allowed_focus_from_question(question: dict) -> list[str]:
    focus: list[str] = []
    for field in ("cat2", "cat1", "tags"):
        value = str(question.get(field) or "").strip()
        if not value:
            continue
        for part in re.split(r"[,，、/\s]+", value):
            part = part.strip()
            if len(part) >= 2 and part not in focus:
                focus.append(part)
            if len(focus) >= 6:
                return focus
    for token in sorted(_tokenize_for_overlap(str(question.get("question") or "")))[:6]:
        if token not in focus:
            focus.append(token)
    return focus[:6]


def _select_question_for_plan(
    state: ChatState,
    candidates: list[dict],
) -> tuple[dict | None, str]:
    """Select one candidate for hard question-plan binding."""
    negative_terms = state.get("search_negative_terms", []) or []
    viable = [
        q
        for q in candidates
        if isinstance(q, dict)
        and q.get("id")
        and q.get("question")
        and not _candidate_contains_negative_term(q, negative_terms)
    ]
    if not viable:
        return None, "no_viable_candidate"

    if state.get("question_type") == "algorithm_coding":
        for candidate in viable:
            if _is_algorithm_candidate(candidate):
                return candidate, "algorithm_candidate_match"

    return viable[0], "top_ranked_candidate"


def _maybe_create_question_plan(state: ChatState) -> dict | None:
    """Create next_question_plan from current candidates when the turn needs a new question."""
    if not _should_create_question_plan(state):
        return None

    candidates = state.get("candidate_questions") or state.get("retrieved_questions") or []
    selected, selection_reason = _select_question_for_plan(state, candidates)
    if not selected:
        state["question_plan_reason"] = selection_reason
        return None

    plan = {
        "must_ask": True,
        "question_id": selected.get("id"),
        "question_text": str(selected.get("question") or ""),
        "basis_type": "drawn_question" if state.get("question_source") == "draw" else "interview_question",
        "source": state.get("question_source") or "search",
        "strategy": state.get("intent") or "new_question",
        "allowed_focus": _allowed_focus_from_question(selected),
        "forbidden_focus": state.get("search_negative_terms", []) or [],
        "selection_reason": selection_reason,
    }
    state["selected_question"] = selected
    state["next_question_plan"] = plan
    state["question_source_reason"] = "question_plan_bound"
    return plan
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestQuestionPlanHelpers -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add backend/app/agents/chat/pipeline.py backend/tests/chat/test_react_loop.py
git commit -m "feat(backend): select question plans for new chat turns"
```

---

## Task 5: Inject plans, enforce adherence, and repair drift

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: Add failing tests for plan injection and repair**

Append to `TestQuestionPlanHelpers` or create `TestQuestionPlanEnforcement` in `backend/tests/chat/test_react_loop.py`:

```python
class TestQuestionPlanEnforcement:
    async def test_final_generation_injects_next_question_plan(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "来一道 RAG 题",
            "model": None,
            "intent": "practice_request",
            "answer_complete": False,
        }
        tc_search = _tc("search_questions", {"keywords": ["RAG"]})
        captured_messages = []

        async def mock_llm(messages, *args, **kwargs):
            captured_messages.append(messages)
            if len(captured_messages) == 1:
                return {"content": None, "tool_calls": [tc_search], "finish_reason": "tool_calls"}
            return {"content": "请你说说 RAG 检索怎么设计？", "tool_calls": None, "finish_reason": "stop"}

        async def mock_execute_tool(tc, st):
            question = {"id": 11, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "tags": "检索", "sources": []}
            st["retrieved_questions"] = [question]
            st["candidate_questions"] = [question]
            st["question_source"] = "search"
            return json.dumps({
                "ok": True,
                "tool": "search_questions",
                "items": [{**question, "source": "search", "score": 0.1, "reason": "rrf_ranked"}],
                "metadata": {"result_count": 1, "fallback_used": False, "fallback_steps": [], "empty_reason": None, "debug_reason": "hybrid_search_ok", "metrics": {"total_ms": 1}},
                "error": None,
            }, ensure_ascii=False)

        with (
            patch("app.agents.chat.pipeline.build_react_system_prompt", return_value="Prompt."),
            patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm),
            patch("app.agents.chat.pipeline.execute_tool", side_effect=mock_execute_tool),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        second_messages_text = "\n".join(m.get("content") or "" for m in captured_messages[1])
        assert "<next_question_plan>" in second_messages_text
        assert "RAG 检索怎么设计" in second_messages_text
        assert state["next_question_plan"]["question_id"] == 11

    async def test_plan_drift_is_repaired_once(self):
        from app.agents.chat.pipeline import _final_answer_events_from_text

        state = {
            "user_id": 1,
            "user_message": "来一道 RAG 题",
            "next_question_plan": {
                "must_ask": True,
                "question_id": 11,
                "question_text": "RAG 检索怎么设计？",
                "basis_type": "interview_question",
                "source": "search",
                "strategy": "practice_request",
                "allowed_focus": ["RAG", "检索"],
                "forbidden_focus": ["HR"],
                "selection_reason": "top_ranked_candidate",
            },
            "selected_question": {"id": 11, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG"},
        }

        with patch(
            "app.agents.chat.pipeline._repair_response_to_question_plan",
            new_callable=AsyncMock,
            return_value={
                "response": "我们收束到 RAG：请你说说 RAG 检索怎么设计？",
                "repaired": True,
                "reason": "plan_drift_repaired",
                "adherence": {"adheres": True, "score": 0.5, "reason": "keyword_overlap"},
            },
        ) as mock_repair:
            events = await _final_answer_events_from_text("说说你的 HR 优势？", state)

        assert events[0]["type"] == "chunk"
        assert "RAG 检索怎么设计" in events[0]["content"]
        assert state["question_plan_metadata"]["repaired"] is True
        mock_repair.assert_awaited_once()
```

If `_final_answer_events_from_text` is synchronous when this task starts, the implementation step will make it async. Update existing call sites and tests accordingly as described below.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestQuestionPlanEnforcement -q
```

Expected: FAIL because plan injection/enforcement is not implemented.

- [ ] **Step 3: Import plan helpers from nodes.py**

In `backend/app/agents/chat/pipeline.py`, extend the existing import from `app.agents.chat.nodes` at the top to include:

```python
    _build_next_question_plan_prompt,
    _question_plan_adherence,
    _repair_response_to_question_plan,
```

- [ ] **Step 4: Add async plan enforcement helper**

Add after `_ensure_final_answer_quality()`:

```python
async def _enforce_question_plan_on_text(
    text: str,
    state: ChatState,
) -> str:
    """Verify final text follows next_question_plan; repair once if it drifts."""
    plan = state.get("next_question_plan")
    if not plan or not plan.get("must_ask"):
        return text

    adherence = _question_plan_adherence(text, plan)
    metadata = {
        "question_id": plan.get("question_id"),
        "source": plan.get("source"),
        "selection_reason": plan.get("selection_reason"),
        "adherence": adherence,
        "repaired": False,
    }
    if adherence.get("adheres"):
        state["question_plan_metadata"] = metadata
        return text

    repair = await _repair_response_to_question_plan(
        user_id=state.get("user_id"),
        user_message=str(state.get("user_message") or ""),
        original_response=text,
        plan=plan,
    )
    repaired_text = str(repair.get("response") or "").strip()
    repaired_adherence = repair.get("adherence") or _question_plan_adherence(repaired_text, plan)
    metadata.update({
        "adherence": repaired_adherence,
        "repaired": True,
        "repair_reason": repair.get("reason", "plan_drift_repaired"),
    })

    if repaired_text and repaired_adherence.get("adheres"):
        state["question_plan_metadata"] = metadata
        state["question_source_reason"] = "question_plan_repaired"
        return repaired_text

    fallback = (
        f"我们收束到这道题：{plan.get('question_text', '')}\n\n"
        "请你说明核心思路、关键取舍，以及你会怎么验证这个方案。"
    )
    metadata["fallback_used"] = True
    metadata["adherence"] = _question_plan_adherence(fallback, plan)
    state["question_plan_metadata"] = metadata
    state["question_source_reason"] = "question_plan_fallback"
    return fallback
```

- [ ] **Step 5: Make final-answer conversion async**

Change function definition:

```python
async def _final_answer_events_from_text(
    final_text: str,
    state: ChatState,
) -> list[dict]:
```

Inside it, after `_ensure_final_answer_quality(...)`, add:

```python
    final_text = await _enforce_question_plan_on_text(final_text, state)
```

Update all call sites in `_react_loop()` from:

```python
for event in _final_answer_events_from_text(final_answer_text, state):
    yield event
```

to:

```python
for event in await _final_answer_events_from_text(final_answer_text, state):
    yield event
```

Update existing synchronous tests that call `_final_answer_events_from_text` directly. For example, in `TestFinalAnswerQuality.test_bare_coding_prompt_gets_full_fallback_question`, make the test async and call:

```python
        events = await _final_answer_events_from_text("来，写代码吧。", state)
```

- [ ] **Step 6: Inject plan after tool execution and before next LLM call**

In `_react_loop()`, after each search/draw tool execution and before appending the tool result message, create plan when applicable:

```python
            if tool_name in ("search_questions", "draw_questions"):
                _maybe_create_question_plan(state)
```

After appending `messages.append(make_tool_result_message(...))`, append the plan prompt once if it exists and was not already injected:

```python
            plan = state.get("next_question_plan")
            if tool_name in ("search_questions", "draw_questions") and plan and not state.get("question_plan_injected"):
                plan_prompt = _build_next_question_plan_prompt(plan)
                if plan_prompt:
                    messages.append({
                        "role": "user",
                        "content": "[系统自动生成的下一题约束]\n" + plan_prompt,
                    })
                    state["question_plan_injected"] = True
```

- [ ] **Step 7: Ensure streamed final answers also enforce plan**

In `_stream_final_answer()`, after:

```python
    final_text = _ensure_final_answer_quality(final_text, state)
```

add:

```python
    final_text = await _enforce_question_plan_on_text(final_text, state)
```

- [ ] **Step 8: Run plan enforcement tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestQuestionPlanEnforcement -q
```

Expected: PASS.

- [ ] **Step 9: Run all ReAct loop tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py -q
```

Expected: PASS. If older direct `_final_answer_events_from_text` tests fail because the helper became async, update them to async and `await` as described in Step 5.

- [ ] **Step 10: Commit Task 5**

```bash
git add backend/app/agents/chat/pipeline.py backend/tests/chat/test_react_loop.py
git commit -m "feat(backend): enforce selected question plans in react loop"
```

---

## Task 6: Prefer question plan in metadata

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: Add failing metadata priority tests**

Append to `TestQuestionPlanEnforcement`:

```python
    def test_react_metadata_prefers_planned_selected_question(self):
        from app.agents.chat.pipeline import _build_react_metadata

        state = {
            "retrieved_questions": [
                {"id": 1, "question": "Redis 持久化怎么做？", "cat1": "后端", "cat2": "Redis", "sources": []},
                {"id": 2, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "sources": []},
            ],
            "candidate_questions": [
                {"id": 1, "question": "Redis 持久化怎么做？", "cat1": "后端", "cat2": "Redis", "sources": []},
                {"id": 2, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "sources": []},
            ],
            "selected_question": {"id": 2, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "sources": []},
            "next_question_plan": {
                "must_ask": True,
                "question_id": 2,
                "question_text": "RAG 检索怎么设计？",
                "source": "search",
                "selection_reason": "top_ranked_candidate",
            },
            "question_plan_metadata": {
                "adherence": {"adheres": True, "score": 0.5, "reason": "keyword_overlap"},
                "repaired": False,
            },
            "question_source": "search",
            "question_source_reason": "question_plan_bound",
            "active_skills": [],
        }

        metadata, clean = _build_react_metadata(state, "请你说说 Redis 持久化？")

        assert metadata["selected_question"]["id"] == 2
        assert metadata["question_source_reason"] == "question_plan_bound"
        assert metadata["question_plan"]["repaired"] is False
        assert clean == "请你说说 Redis 持久化？"
```

- [ ] **Step 2: Run metadata test to verify it fails**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestQuestionPlanEnforcement::test_react_metadata_prefers_planned_selected_question -q
```

Expected: FAIL because `_build_react_metadata()` still infers selected question from response/basis first or lacks `question_plan` metadata.

- [ ] **Step 3: Update metadata priority**

In `_build_react_metadata()`, before calling `_infer_selected_question(...)`, add:

```python
    plan = state.get("next_question_plan") or {}
    plan_metadata = state.get("question_plan_metadata") or {}
    selected_question = None
    selected_reason = ""

    if (
        plan.get("must_ask")
        and state.get("selected_question")
        and (
            plan_metadata.get("adherence", {}).get("adheres")
            or plan_metadata.get("repaired")
            or state.get("question_source_reason") in {"question_plan_bound", "question_plan_repaired", "question_plan_fallback"}
        )
    ):
        selected_question = state.get("selected_question")
        selected_reason = state.get("question_source_reason") or "question_plan_bound"
    else:
        selected_question, selected_reason = _infer_selected_question(
            clean_response,
            basis["basis_question_ids"],
            candidates,
        )
```

Then remove or replace the existing later block that starts with:

```python
    selected_question, selected_reason = _infer_selected_question(
```

Keep the existing fallback:

```python
    if not selected_question and state.get("selected_question"):
        selected_question = state.get("selected_question")
        selected_reason = state.get("question_source_reason") or "state_selected_question"
```

After candidate metadata, add:

```python
    if plan:
        metadata["question_plan"] = {
            "question_id": plan.get("question_id"),
            "source": plan.get("source"),
            "selection_reason": plan.get("selection_reason"),
            "adherence": plan_metadata.get("adherence"),
            "repaired": bool(plan_metadata.get("repaired", False)),
            "fallback_used": bool(plan_metadata.get("fallback_used", False)),
        }
```

- [ ] **Step 4: Run metadata test**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py::TestQuestionPlanEnforcement::test_react_metadata_prefers_planned_selected_question -q
```

Expected: PASS.

- [ ] **Step 5: Run all chat tests touched so far**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_tools.py backend/tests/chat/test_react_loop.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add backend/app/agents/chat/pipeline.py backend/tests/chat/test_react_loop.py
git commit -m "fix(backend): prefer planned selected question metadata"
```

---

## Task 7: Update backend documentation and development log

**Files:**
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Modify: `backend/tests/chat/CLAUDE.md`
- Create: `docs/dev-log/2026-06-22-chat-tools-gateway-question-plan.md`

- [ ] **Step 1: Update chat agent CLAUDE.md**

In `backend/app/agents/chat/CLAUDE.md`, add rows to the file responsibility table:

```markdown
| `tools.py` | ReAct tool schemas and tool execution entrypoint |
| `tool_gateway.py` | Tool input/output contracts, envelope normalization, and tool error metadata |
```

Under “质量保护机制”, add:

```markdown
- **Tool Gateway 契约**：`search_questions` / `draw_questions` 通过 `tool_gateway.py` 返回统一 `ok/items/metadata/error` envelope，同时保持 `retrieved_questions` 和 SSE retrieved 兼容
- **题目计划绑定**：出新题场景会从候选题中本地选择 `selected_question`，生成 `next_question_plan` 注入最终生成；偏离计划时触发一次 repair，仍失败则使用确定性 fallback
```

- [ ] **Step 2: Update chat tests CLAUDE.md**

In `backend/tests/chat/CLAUDE.md`, add or update rows:

```markdown
| `test_tools.py` | ReAct tools、Tool Gateway envelope、工具执行副作用 |
| `test_react_loop.py` | ReAct 主循环、tool governance、question plan 绑定与 repair |
```

- [ ] **Step 3: Create dev log**

Create `docs/dev-log/2026-06-22-chat-tools-gateway-question-plan.md`:

```markdown
# 2026-06-22 Chat Tools Gateway 与题目计划绑定实现

## 变更摘要

- 新增 `backend/app/agents/chat/tool_gateway.py`，统一 chat tools 的输入校验、题目 item 规范化、成功/失败 envelope。
- `search_questions` / `draw_questions` 返回 `ok/items/metadata/error` 结构，同时保持 legacy state：`retrieved_questions`、`candidate_questions`、`question_source`。
- ReAct loop 支持 envelope 解析、trace summary、tool result top-3 裁剪。
- 出新题场景新增 `next_question_plan`：本地选择 `selected_question`、注入生成约束、生成后做 adherence 校验。
- 偏离计划时触发一次 repair；repair 仍失败时使用确定性 fallback。
- metadata 优先使用计划绑定的 `selected_question`。

## 测试命令

```bash
docker compose exec backend uv run pytest backend/tests/chat/test_tools.py -q
docker compose exec backend uv run pytest backend/tests/chat/test_react_loop.py -q
docker compose exec backend uv run pytest backend/tests/chat/ -q
docker compose exec backend uv run pytest backend/tests/ -q
```

## README 检查

本次未新增 API、路由、数据库迁移、环境变量、前端入口或部署方式，通常不需要更新 README。
```

- [ ] **Step 4: Commit docs**

```bash
git add backend/app/agents/chat/CLAUDE.md backend/tests/chat/CLAUDE.md docs/dev-log/2026-06-22-chat-tools-gateway-question-plan.md
git commit -m "docs: document chat tools gateway implementation"
```

---

## Task 8: Run final gates and fix regressions

**Files:**
- Modify only files needed to fix failing tests from this plan.

- [ ] **Step 1: Run focused chat tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/chat/ -q
```

Expected: PASS.

- [ ] **Step 2: Run service tests if service files changed**

If implementation changed `backend/app/services/fts_service.py` or `backend/app/services/question_draw_service.py`, run:

```bash
docker compose exec backend uv run pytest backend/tests/services/ -q
```

Expected: PASS.

If no service files changed, record “skipped: no service code changed” in the final response.

- [ ] **Step 3: Run full backend tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/ -q
```

Expected: PASS. If unrelated pre-existing failures appear, capture exact failing test names and output summary before deciding whether to fix or report.

- [ ] **Step 4: Check README update requirement**

Review `.claude/rules/readme-checklist.md`. For this plan, README update is not required unless implementation added one of these:

- new API route
- new frontend service/component/view
- database table/migration
- environment variable
- deployment or dependency change

If none apply, do not edit README.

- [ ] **Step 5: Check working tree includes only intended files**

Run:

```bash
git status --short
```

Expected: only intended files for the current task are modified/staged. Do not stage unrelated pre-existing frontend/deploy/lockfile changes.

- [ ] **Step 6: Commit any final test fixes**

If final gate fixes were needed:

```bash
git add <only-files-changed-for-this-plan>
git commit -m "fix(backend): stabilize chat tool plan tests"
```

If no fixes were needed, do not create an empty commit.

---

## Self-review checklist

- Spec coverage:
  - Tool Gateway input/output models: Tasks 1-2.
  - Unified envelope and errors: Tasks 1-2.
  - Metrics total_ms: Tasks 1-2.
  - State/SSE compatibility: Task 3.
  - selected_question plan creation: Task 4.
  - Plan injection, adherence, repair, fallback: Task 5.
  - Metadata priority: Task 6.
  - Docs/dev-log: Task 7.
  - Final Docker gates: Task 8.
- No service signature changes are required.
- No frontend work is required.
- No README update is expected unless implementation scope expands.
- Each implementation task has a failing-test step, a passing-test step, and a commit step.

"""Multi-turn E2E test fixtures for the chat agent pipeline.

Provides MultiTurnRunner that orchestrates N-turn interview sessions,
collecting SSE events and state snapshots for assertion.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Data Classes ──────────────────────────────────────


@dataclass
class TurnSpec:
    """Specification for one turn in a multi-turn interview."""

    user_message: str
    classify_updates: dict
    llm_responses: list[dict]
    stream_chunks: tuple[str, ...]
    tool_patches: list = field(default_factory=list)


@dataclass
class TurnResult:
    """Result of a single turn execution."""

    events: list[dict]
    state_snapshot: dict
    llm_mock: AsyncMock


@dataclass
class InterviewResult:
    """Aggregated result of a multi-turn interview session."""

    turns: list[TurnResult] = field(default_factory=list)

    @property
    def all_events(self) -> list[dict]:
        return [e for t in self.turns for e in t.events]

    @property
    def event_types_by_turn(self) -> list[list[str]]:
        return [[e["type"] for e in t.events] for t in self.turns]

    @property
    def basis_events(self) -> list[dict]:
        return [e for e in self.all_events if e["type"] == "basis"]

    @property
    def retrieved_events(self) -> list[dict]:
        return [e for e in self.all_events if e["type"] == "retrieved"]

    @property
    def insight_events(self) -> list[dict]:
        return [e for e in self.all_events if e["type"] == "insight"]

    @property
    def step_events(self) -> list[dict]:
        return [e for e in self.all_events if e["type"] == "step"]

    @property
    def chunk_events(self) -> list[dict]:
        return [e for e in self.all_events if e["type"] == "chunk"]

    @property
    def done_events(self) -> list[dict]:
        return [e for e in self.all_events if e["type"] == "done"]

    def steps_by_turn(self, turn_idx: int) -> list[str]:
        return [
            e["step"]
            for e in self.turns[turn_idx].events
            if e["type"] == "step"
        ]

    def basis_by_turn(self, turn_idx: int) -> dict | None:
        for e in self.turns[turn_idx].events:
            if e["type"] == "basis":
                return e
        return None

    def response_text(self, turn_idx: int) -> str:
        return "".join(
            e.get("content", "")
            for e in self.turns[turn_idx].events
            if e["type"] == "chunk"
        )


# ── Helpers ───────────────────────────────────────────


def tool_call(name: str, args: dict, tc_id: str = "call_1") -> dict:
    """Build an OpenAI-style tool call dict."""
    return {
        "id": tc_id,
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }


def stream_chunks(*chunks: str):
    """Create an async generator that yields text chunks."""
    async def _gen():
        for chunk in chunks:
            yield chunk
    return _gen()


async def mock_stream(*chunks: str):
    for c in chunks:
        yield c


async def _async_stream(*chunks: str):
    """Async generator for stream_llm_messages mock."""
    for c in chunks:
        yield c


def make_question(
    qid: int,
    question: str,
    *,
    cat1: str = "中间件",
    cat2: str = "缓存",
    company: str = "腾讯",
    round_name: str = "一面",
) -> dict:
    """Build a mock question dict matching question_draw_service format."""
    return {
        "id": qid,
        "question": question,
        "cat1": cat1,
        "cat2": cat2,
        "tags": "redis,cache",
        "sources": [{"company": company, "round": round_name}],
    }


def routerize_events(events: list[dict]) -> list[dict]:
    """Mirror the router's SSE conversion for run_chat event stream."""
    sse_events: list[dict] = []
    for event in events:
        event_type = event.get("type")
        if event_type == "basis":
            continue
        if event_type == "done":
            meta = event.get("metadata", {})
            basis_type = meta.get("basis_type")
            if basis_type:
                sse_events.append(
                    {
                        "type": "basis",
                        "basis_type": basis_type,
                        "basis_question_ids": meta.get("basis_question_ids", []),
                        "basis_confidence": meta.get("basis_confidence", 0.0),
                        "should_show_references": meta.get(
                            "should_show_references", False
                        ),
                        "selected_basis_questions": meta.get(
                            "selected_basis_questions", []
                        ),
                        "resume_ref": meta.get("resume_ref", ""),
                        "jd_ref": meta.get("jd_ref", ""),
                    }
                )
            if meta.get("resume_ref"):
                sse_events.append({"type": "resume_ref", "name": meta["resume_ref"]})
            if meta.get("jd_ref"):
                sse_events.append({"type": "jd_ref", "title": meta["jd_ref"]})
            sse_events.append({"type": "done"})
            continue
        sse_events.append(event)
    return sse_events


# ── Multi-Turn Runner ─────────────────────────────────


async def run_single_turn(
    *,
    user_message: str,
    classify_updates: dict,
    llm_responses: list[dict],
    stream_chunks: tuple[str, ...],
    tool_patches: list = None,
    state_overrides: dict | None = None,
    mode: str = "free_practice",
    bank_mode: str = "public",
) -> tuple[list[dict], dict, AsyncMock]:
    """Run a single turn through the pipeline and return (events, state, llm_mock)."""
    from app.agents.chat.pipeline import run_chat

    captured_state: dict = {}
    state_ready = asyncio.Event()

    async def mock_load_context(state):
        state.update(
            {
                "message_history": [],
                "recent_messages": [],
                "compressed_context": None,
                "session_notes": "",
                "interview_context": "目标岗位：后端开发",
                "job_position": "后端开发",
                "memory_summaries": [],
                "retrieved_questions": [],
            }
        )
        if state_overrides:
            state.update(state_overrides)
        return state

    async def mock_classify(state):
        state.update(classify_updates)
        # Older E2E cases describe only the legacy top-level fields.  The
        # production classifier bridges those into classify_result before the
        # planner runs, so mirror that bridge rather than exercising an
        # impossible half-populated state.
        if "classify_result" not in classify_updates:
            intent = classify_updates.get("intent", "interview_question")
            answer_complete = bool(classify_updates.get("answer_complete", False))
            state["classify_result"] = {
                "intent": intent,
                "answer_quality": classify_updates.get(
                    "answer_quality",
                    "complete" if answer_complete else "incomplete",
                ),
                "should_retrieve": bool(classify_updates.get("should_retrieve", False)),
                "needs_new_dimension": bool(
                    classify_updates.get(
                        "needs_new_dimension",
                        answer_complete or intent == "practice_request",
                    )
                ),
                "confidence": float(classify_updates.get("confidence", 0.9)),
            }
        return state

    async def mock_extract_memory(snapshot):
        captured_state.clear()
        captured_state.update(snapshot)
        state_ready.set()

    llm_mock = AsyncMock(side_effect=llm_responses)

    def stream_side_effect(*args, **kwargs):
        return _async_stream(*stream_chunks)

    patchers = [
        patch(
            "app.agents.chat.nodes.build_react_system_prompt",
            return_value="Test ReAct prompt.",
        ),
        patch(
            "app.agents.chat.pipeline._step_load_context",
            new_callable=AsyncMock,
            side_effect=mock_load_context,
        ),
        patch(
            "app.agents.chat.pipeline._step_classify",
            new_callable=AsyncMock,
            side_effect=mock_classify,
        ),
        patch(
            "app.agents.chat.pipeline._step_extract_memory",
            new_callable=AsyncMock,
            side_effect=mock_extract_memory,
        ),
        patch("app.services.llm.llm_with_tools", new=llm_mock),
        patch(
            "app.services.llm.stream_llm_messages",
            side_effect=stream_side_effect,
        ),
    ]
    if tool_patches:
        patchers.extend(tool_patches)

    with ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)

        raw_events: list[dict] = []
        async for event in run_chat(
            conversation_id="conv-multi-turn",
            user_id=1,
            user_message=user_message,
            mode=mode,
            bank_mode=bank_mode,
        ):
            raw_events.append(event)

    await asyncio.wait_for(state_ready.wait(), timeout=1)
    return routerize_events(raw_events), captured_state, llm_mock


async def run_multi_turn_interview(
    turns: list[TurnSpec],
    *,
    mode: str = "free_practice",
    bank_mode: str = "public",
) -> InterviewResult:
    """Run a multi-turn interview session, collecting results for each turn."""
    result = InterviewResult()

    for turn in turns:
        events, state, llm_mock = await run_single_turn(
            user_message=turn.user_message,
            classify_updates=turn.classify_updates,
            llm_responses=turn.llm_responses,
            stream_chunks=turn.stream_chunks,
            tool_patches=turn.tool_patches,
            mode=mode,
            bank_mode=bank_mode,
        )
        result.turns.append(
            TurnResult(events=events, state_snapshot=state, llm_mock=llm_mock)
        )

    return result

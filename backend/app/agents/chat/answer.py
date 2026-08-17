"""Answer generation, deduplication, and quality checks.

Split from pipeline.py — contains output dedup, final answer streaming,
fallback responses, and quality enforcement.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
import time
from typing import AsyncGenerator

from app.agents.chat.nodes import (
    _question_plan_adherence,
    _repair_response_to_question_plan,
)
from app.agents.chat.state import ChatState
from app.agents.chat.tools import SKILL_NAMES
from app.agents.shared.events import _event_queue_var
from app.services import llm as llm_service

logger = logging.getLogger("interview-boss")


class GenerationError(Exception):
    """自然问题生成失败时抛出。

    替代机械题干 fallback，让调用方明确感知失败。
    """

    def __init__(
        self,
        code: str,
        message: str,
        guard: str | None = None,
    ):
        self.code = code
        self.message = message
        self.guard = guard
        super().__init__(message)

_INTERNAL_REACT_MARKERS = frozenset(
    {
        "load_skill",
        "search_questions",
        "draw_questions",
        *SKILL_NAMES,
    }
)

_TRACE_STRING_LIMIT = 120
_UNREQUESTED_SUMMARY_MARKERS = (
    "面试总结",
    "面试评价",
    "整体表现",
    "综合评分",
    "评估基础",
    "整体判断",
)
_END_REQUEST_MARKERS = (
    "结束面试",
    "面试结束",
    "结束这轮",
    "到此结束",
    "到这里结束",
    "收尾",
    "总结",
    "评价",
    "评估",
    "复盘",
)


# ── Output Deduplication (hash + Jaccard) ─────────────────


class OutputDeduplicator:
    """Two-level dedup: hash exact match + Jaccard fuzzy match.
    Borrowed from OpenCode ACP (hash) + Manneri (Jaccard)."""

    def __init__(self, window_size: int = 8, jaccard_threshold: float = 0.7):
        self.hash_buffer: set[str] = set()
        self.token_buffer: list[set[str]] = []
        self.window_size = window_size
        self.jaccard_threshold = jaccard_threshold

    def check(self, text: str) -> str:
        """Return 'exact' | 'similar' | 'ok'"""
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        # Level 1: Hash exact match
        h = hashlib.md5(normalized.encode()).hexdigest()
        if h in self.hash_buffer:
            return "exact"
        # Level 2: Jaccard fuzzy match
        tokens = set(normalized.split())
        if len(tokens) >= 5:
            for prev in self.token_buffer:
                union = tokens | prev
                if not union:
                    continue
                jaccard = len(tokens & prev) / len(union)
                if jaccard >= self.jaccard_threshold:
                    return "similar"
        return "ok"

    def record(self, text: str):
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        self.hash_buffer.add(hashlib.md5(normalized.encode()).hexdigest())
        tokens = set(normalized.split())
        self.token_buffer.append(tokens)
        if len(self.token_buffer) > self.window_size:
            self.token_buffer.pop(0)


# ── Event Emission ────────────────────────────────────────


def _emit(event: dict) -> None:
    queue = _event_queue_var.get()
    if queue:
        queue.put_nowait(event)


# ── Answer Quality ────────────────────────────────────────


def _is_bare_coding_prompt(text: str, state: ChatState) -> bool:
    stripped = (text or "").strip()
    if len(stripped) > 40:
        return False
    wants_coding = (
        "algorithm-coding" in state.get("active_skills", [])
        or state.get("question_type") == "algorithm_coding"
        or bool(re.search(r"(写代码|手撕|代码题|coding)", stripped, re.I))
    )
    if not wants_coding:
        return False
    return bool(re.search(r"(写代码|手撕|代码题|coding)", stripped, re.I))


def _fallback_coding_question(state: ChatState) -> str:
    candidates = (
        state.get("candidate_questions") or state.get("retrieved_questions") or []
    )
    coding_candidate = None
    for q in candidates:
        haystack = " ".join(
            str(q.get(k) or "") for k in ("question", "cat1", "cat2", "tags")
        )
        if re.search(r"(算法|代码|手撕|数据结构|链表|排序|二分)", haystack, re.I):
            coding_candidate = q
            break
    if coding_candidate:
        state["selected_question"] = coding_candidate
        state["question_source"] = "bank"
        state["question_source_reason"] = "fallback_selected_coding_candidate"
        return (
            f"来写一道代码题：{coding_candidate.get('question', '')}\n\n"
            "请直接写代码，并说明你的数据结构选择、关键边界条件，以及时间和空间复杂度。"
        )
    state["question_source"] = state.get("question_source") or "generated"
    state["question_source_reason"] = "fallback_generated_coding_question"
    return (
        "好，来写一道代码题。请根据候选人的技术栈和之前的面试内容，"
        "选择一道合适的手撕题（不要重复之前问过的方向）。"
        "要求候选人写代码并说明设计思路。"
    )


def _ensure_final_answer_quality(text: str, state: ChatState) -> str:
    if _is_bare_coding_prompt(text, state):
        logger.warning(
            "ReAct trace: event=bare_coding_prompt_fallback conversation_id=%s",
            state.get("conversation_id"),
        )
        return _fallback_coding_question(state)
    if _is_unrequested_summary(text, state):
        logger.warning(
            "ReAct trace: event=unrequested_summary_fallback conversation_id=%s",
            state.get("conversation_id"),
        )
        return _fallback_react_answer(state, "unrequested_summary")
    return text


def _is_unrequested_summary(text: str, state: ChatState) -> bool:
    if not text or state.get("intent") == "end_interview":
        return False
    stop_decision = state.get("interview_stop_decision") or {}
    if isinstance(stop_decision, dict) and stop_decision.get("action") == "close":
        return False
    user_message = str(state.get("user_message") or "")
    if any(marker in user_message for marker in _END_REQUEST_MARKERS):
        return False
    marker_count = sum(1 for marker in _UNREQUESTED_SUMMARY_MARKERS if marker in text)
    return marker_count >= 2 or "## 面试总结" in text or "## 面试评价" in text


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

    pipeline_module = sys.modules.get("app.agents.chat.pipeline")
    repair_fn = getattr(
        pipeline_module,
        "_repair_response_to_question_plan",
        _repair_response_to_question_plan,
    )
    repair = await repair_fn(
        user_id=state.get("user_id"),
        user_message=str(state.get("user_message") or ""),
        original_response=text,
        plan=plan,
    )
    repaired_text = str(repair.get("response") or "").strip()
    repaired_adherence = repair.get("adherence") or _question_plan_adherence(
        repaired_text, plan
    )
    metadata.update(
        {
            "adherence": repaired_adherence,
            "repaired": True,
            "repair_reason": repair.get("reason", "plan_drift_repaired"),
        }
    )

    if repaired_text and repaired_adherence.get("adheres"):
        state["question_plan_metadata"] = metadata
        state["question_source_reason"] = "question_plan_repaired"
        return repaired_text

    # Try LLM rewrite for natural transition
    # Phase 5: tightened — rewrite must also adhere to plan, otherwise raise GenerationError
    question_text = str(plan.get("question_text") or "")
    last_answer = str(state.get("user_message") or "")
    rewritten = await _rewrite_transition_with_llm(question_text, last_answer)
    if rewritten:
        rewritten_adherence = _question_plan_adherence(rewritten, plan)
        if rewritten_adherence.get("adheres"):
            metadata["fallback_used"] = True
            metadata["adherence"] = rewritten_adherence
            metadata["transition_source"] = "llm_rewrite"
            state["question_plan_metadata"] = metadata
            state["question_source_reason"] = "question_plan_llm_rewrite"
            return rewritten
        # Rewrite drifted — don't accept it
        logger.warning(
            "Rewrite transition drifted: adherence=%s question_text=%r",
            rewritten_adherence,
            question_text,
        )

    # Mechanical fallback removed — raise explicit error instead
    metadata["fallback_used"] = True
    metadata["transition_source"] = "generation_error"
    state["question_plan_metadata"] = metadata
    state["question_source_reason"] = "question_plan_generation_error"
    raise GenerationError(
        code="question_plan_generation_failed",
        message=(
            f"Question plan enforcement failed: LLM rewrite unavailable; "
            f"plan question_text={question_text!r}"
        ),
        guard="no_mechanical_question",
    )


# ── Fallback & Marker Detection ───────────────────────────


def _normalize_react_marker(text: str) -> str:
    return text.strip().strip("`'\"''").lower()


def _is_internal_react_marker(text: str) -> bool:
    normalized = _normalize_react_marker(text)
    if not normalized:
        return False
    return normalized in _INTERNAL_REACT_MARKERS


def _fallback_interviewer_response(marker: str, state: ChatState) -> str:
    """Replace leaked internal markers with a safe interviewer turn."""
    normalized = _normalize_react_marker(marker)
    logger.warning(
        "ReAct trace: event=internal_marker_filtered conversation_id=%s marker=%s",
        state.get("conversation_id"),
        normalized[:_TRACE_STRING_LIMIT],
    )

    if normalized == "project-deep-dive":
        return (
            "我们继续围绕你的项目做深挖。你刚才提到“AI 追问编排”和“题库/JD 匹配”，"
            "请具体讲一下：一次候选人回答进入后端后，从意图判断、关键词提取、题库检索到生成追问，"
            "完整链路是怎么设计的？中间你做过哪些取舍？"
        )

    if normalized == "algorithm-coding":
        return (
            "我们切到算法面试。我会先从基础思路开始考察：请你口述一下两数之和这类题的解法，"
            "包括数据结构选择、时间复杂度和边界情况。"
        )

    return (
        "我继续追问一个具体问题：请结合你刚才的项目，说明其中一个核心模块的设计方案、"
        "关键取舍，以及你如何验证它确实解决了问题。"
    )


# ── Natural transition via LLM rewrite ──────────────────────────

_TRANSITION_REWRITE_SYSTEM = (
    "你是技术面试官。候选人刚回答了一段话，你需要自然地过渡到下一道题。\n"
    "规则：\n"
    "1. 用 1-2 句话从候选人的回答自然过渡到新题目\n"
    "2. 可以引用候选人提到的具体技术点做承接\n"
    "3. 禁止使用 '换个方向'、'换个问题'、'换个具体点的问题'、'换个角度' 这类机械前缀\n"
    "4. 直接输出面试官的话，不要加任何前缀、解释或 markdown 格式\n"
    "5. 保持面试官冷峻、务实的语气"
)


async def _rewrite_transition_with_llm(
    question_text: str,
    last_user_answer: str,
) -> str | None:
    """Use LLM to generate a natural transition from candidate's answer to the next question.

    Returns the rewritten text, or None if LLM fails.
    """
    if not question_text.strip():
        return None
    messages = [
        {"role": "system", "content": _TRANSITION_REWRITE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"候选人刚才的回答：{last_user_answer[:300]}\n\n"
                f"下一道题：{question_text}\n\n"
                "请生成自然的过渡。"
            ),
        },
    ]
    try:
        chunks: list[str] = []
        async for event in llm_service.stream_llm_messages(
            messages, temperature=0.3, max_tokens=200
        ):
            if event.get("type") == "chunk":
                chunks.append(str(event.get("content") or ""))
        text = "".join(chunks).strip()
        # Validate: must be non-empty, not leaked markers, not mechanical prefixes
        if (
            text
            and len(text) > 5
            and "换个具体点的问题" not in text
            and "换个方向" not in text
        ):
            return text
    except Exception:
        logger.warning("transition rewrite LLM call failed", exc_info=True)
    return None


def _fallback_react_answer(state: ChatState, reason: str) -> str:
    """Return a safe interviewer turn when ReAct/tool/final generation fails.

    Raises GenerationError instead of generating mechanical question fallback
    when candidate questions are available.
    """
    candidates = (
        state.get("candidate_questions") or state.get("retrieved_questions") or []
    )
    if candidates:
        selected = candidates[0]
        state["selected_question"] = selected
        state["question_source"] = state.get("question_source") or "search"
        state["question_source_reason"] = f"fallback_after_{reason}"
        raise GenerationError(
            code="mechanical_fallback_blocked",
            message=(
                f"ReAct fallback blocked for reason={reason}; "
                f"candidate question available: {selected.get('question', '')}"
            ),
            guard="no_mechanical_question",
        )

    state["question_source"] = "conversation"
    state["question_source_reason"] = f"fallback_after_{reason}"
    keywords = state.get("keywords") or []
    topic = "、".join(keywords[:3]) if keywords else "你刚才提到的项目"
    return (
        f"我们先围绕「{topic}」问细一点。挑一个你实际做过的模块，"
        "说清楚它的关键流程和主要取舍。"
    )


def _last_assistant_message(state: ChatState) -> str:
    for msg in reversed(state.get("message_history", []) or []):
        if msg.get("role") == "assistant":
            return str(msg.get("content") or "")
    return ""


def _looks_like_candidate_question(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.endswith(("?", "？")):
        return True
    return bool(re.search(r"(想问|请问|了解一下|团队|实习生|培养|业务|落地)", stripped))


# ── Streaming ─────────────────────────────────────────────


async def _regenerate_after_dup(
    messages: list[dict],
    state: ChatState,
) -> AsyncGenerator[dict, None]:
    """Re-stream after a duplicate output was detected.

    Called once when OutputDeduplicator flags 'exact' or 'similar'.  Streams
    the regenerated answer directly — no second dedup check (one retry only).
    """
    async for event in llm_service.stream_llm_messages(
        messages,
        user_id=state["user_id"],
        model=state.get("model"),
        yield_thinking=False,
    ):
        if isinstance(event, dict):
            if event.get("type") == "content":
                yield {"type": "chunk", "content": event.get("content", "")}
        else:
            yield {"type": "chunk", "content": event}


async def _stream_final_answer(
    messages: list[dict],
    state: ChatState,
) -> AsyncGenerator[dict, None]:
    """Stream final answer while guarding against internal ReAct marker leakage.

    Integrates two-level output dedup (hash + Jaccard) to detect and regenerate
    repeated responses before they reach the user.
    """
    chunks: list[str] = []
    streamed_any = False

    # Track thinking lifecycle for synthesizing thinking_done
    is_thinking = False
    thinking_start_time = None
    thinking_content = ""

    async for event in llm_service.stream_llm_messages(
        messages,
        user_id=state["user_id"],
        model=state.get("model"),
        yield_thinking=True,
    ):
        if isinstance(event, dict):
            event_type = event.get("type")
            content = event.get("content", "")

            if event_type == "thinking_start":
                is_thinking = True
                thinking_start_time = time.time()
                _emit({"type": "thinking_start", "content": ""})
            elif event_type == "thinking":
                thinking_content += content
                _emit({"type": "thinking", "content": content})
            elif event_type == "content":
                if is_thinking:
                    is_thinking = False
                    duration = (
                        round(time.time() - thinking_start_time, 1)
                        if thinking_start_time
                        else 0
                    )
                    _emit(
                        {
                            "type": "thinking_done",
                            "duration": duration,
                            "content": thinking_content,
                        }
                    )
                chunks.append(content)
                if content:
                    streamed_any = True
                    yield {"type": "chunk", "content": content}
        else:
            chunks.append(event)
            if event:
                streamed_any = True
                yield {"type": "chunk", "content": event}

    # Handle case where stream ended while still in thinking mode
    if is_thinking:
        duration = (
            round(time.time() - thinking_start_time, 1) if thinking_start_time else 0
        )
        _emit(
            {
                "type": "thinking_done",
                "duration": duration,
                "content": thinking_content,
            }
        )

    streamed_text = "".join(chunks)
    final_text = streamed_text
    if _is_internal_react_marker(final_text):
        final_text = _fallback_interviewer_response(final_text, state)
    final_text = _ensure_final_answer_quality(final_text, state)
    final_text = await _enforce_question_plan_on_text(final_text, state)

    # Two-level output dedup: check before yielding
    if final_text:
        deduplicator = state.setdefault("output_deduplicator", OutputDeduplicator())
        dup_result = deduplicator.check(final_text)

        if dup_result == "exact":
            logger.info(
                "ReAct trace: event=output_dedup_exact conversation_id=%s",
                state.get("conversation_id"),
            )
            # Inject note and regenerate once
            messages.append(
                {
                    "role": "user",
                    "content": "【系统提示】你刚才的回答和之前的完全相同，请换一个角度或切换话题。",
                }
            )
            first_replacement = streamed_any
            async for event in _regenerate_after_dup(messages, state):
                if first_replacement and event.get("type") == "chunk":
                    event = {**event, "replace": True}
                    first_replacement = False
                yield event
            return
        elif dup_result == "similar":
            logger.info(
                "ReAct trace: event=output_dedup_similar conversation_id=%s",
                state.get("conversation_id"),
            )
            # Inject note and regenerate once
            messages.append(
                {
                    "role": "user",
                    "content": "【系统提示】你刚才的回答和之前的高度相似，请用不同的话术重新回答。",
                }
            )
            first_replacement = streamed_any
            async for event in _regenerate_after_dup(messages, state):
                if first_replacement and event.get("type") == "chunk":
                    event = {**event, "replace": True}
                    first_replacement = False
                yield event
            return
        else:
            deduplicator.record(final_text)

    if final_text and final_text != streamed_text:
        yield {"type": "chunk", "content": final_text, "replace": streamed_any}
    elif final_text and not streamed_any:
        yield {"type": "chunk", "content": final_text}


async def _final_answer_events_from_text(
    final_text: str,
    state: ChatState,
) -> list[dict]:
    """Convert pre-captured LLM answer text into yieldable events.

    Note: dedup for the direct-answer path is handled by _react_loop
    (which has access to messages for regeneration).
    """
    if _is_internal_react_marker(final_text):
        final_text = _fallback_interviewer_response(final_text, state)
    final_text = _ensure_final_answer_quality(final_text, state)
    final_text = await _enforce_question_plan_on_text(final_text, state)
    if not final_text:
        return []
    return [{"type": "chunk", "content": final_text}]

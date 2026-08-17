"""Chat Pipeline — 纯 async pipeline，替代 LangGraph StateGraph。

设计原则（来自业界研究）：
- Graph 做基础设施，LLM 做对话决策
- Skills 是 prompt 注入，不是 graph 节点
- 检索结果是参考资料，不是强制约束
- 简单 if/elif 路由，不需要 state machine
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncGenerator

from app.agents.chat.context_builder import build_interview_context
from app.agents.chat.nodes import (
    _repair_response_to_question_plan,  # noqa: F401 - compatibility re-export
    check_round_limit,
    extract_memory,
    load_history,
    recall_memories,
    summarize_context,
)
from app.agents.chat.state import ChatState
from app.agents.chat.interview_state import build_interview_state_snapshot
from app.agents.shared.events import _event_queue_var
from app.services import chat_service, llm as llm_service
from app.mcp_server.session import save_mcp_session_async
from app.agents.chat.decision_config import get_decision_config
from app.services.memory_recall_service import (
    classify_and_recall,
)

# Re-exports from submodules (backward compatibility for tests and graph.py)
from app.agents.chat.react_loop import (  # noqa: F401
    MAX_REACT_STEPS,
    REACT_BUDGET,
    STEP_REASONS,
    Budget,
    StopRun,
    _ALLOWED_TOOL_NAMES,
    _PERSISTENT_SKILLS,
    _SAFE_TOOL_ARG_KEYS,
    _TRACE_LIST_LIMIT,
    _TRACE_STRING_LIMIT,
    _build_closing_context,
    _generate_close_with_summary,
    _emit,
    _log_react_llm_step,
    _log_react_tool_call,
    _react_loop,
    _sanitize_tool_args,
    _step,
    _summarize_tool_output,
    _trace_safe_value,
    validate_tool_call,
)
from app.agents.chat.answer import (  # noqa: F401
    OutputDeduplicator,
    _INTERNAL_REACT_MARKERS,
    _ensure_final_answer_quality,
    _fallback_coding_question,
    _fallback_interviewer_response,
    _fallback_react_answer,
    _final_answer_events_from_text,
    _is_bare_coding_prompt,
    _is_internal_react_marker,
    _last_assistant_message,
    _looks_like_candidate_question,
    _normalize_react_marker,
    _regenerate_after_dup,
    _stream_final_answer,
)
from app.agents.chat.question_plan import (  # noqa: F401
    InterviewLedger,
    _MAX_CONSECUTIVE_SAME_QUESTION,
    _allowed_focus_from_question,
    _build_interview_ledger,
    _build_previously_asked_section,
    _build_repetition_protection_note,
    _candidate_contains_negative_term,
    _count_consecutive_similar_questions,
    _is_algorithm_candidate,
    _maybe_create_question_plan,
    _normalize_question_text,
    _select_question_for_plan,
    _should_create_question_plan,
    _should_require_bank_question,
    _tokenize_for_overlap,
)
from app.agents.chat.summary import (  # noqa: F401
    _FRIENDLY_ERROR,
    _SUMMARY_SYSTEM_PROMPT,
    _build_interview_transcript,
    _forced_closing_response,
    _generate_end_interview_response,
    _generate_structured_summary,
    _render_interview_summary_markdown,
    _sanitize_error_message,
    InterviewSummary,
)
from app.agents.chat.metadata import (  # noqa: F401
    _basis_event_payload,
    _build_react_metadata,
    _extract_company,
    _extract_round,
    _infer_selected_question,
    _public_question,
)
from app.agents.chat.trace import build_reasoning_trace, merge_trace_metadata
from app.services.llm_usage import aggregate_cache_usage
from app.agents.chat.turn_contract import plan_turn

logger = logging.getLogger("interview-boss")

_SENTINEL = object()
_MAX_THINKING_CHUNKS = 50


def assert_chat_turn_active(state: ChatState) -> None:
    """Validate the durable turn before a pipeline-owned side effect.

    Older synthetic callers do not create a persisted turn, so the guard is a
    no-op for states without a turn identity. HTTP chat requests always carry
    both fields from the router reservation.
    """
    turn_id = state.get("turn_id")
    turn_fence = state.get("turn_fence")
    if not turn_id or turn_fence is None:
        return
    chat_service.assert_chat_turn_active(
        turn_id,
        int(turn_fence),
        state["conversation_id"],
        state["user_id"],
    )


def _initial_state(
    conversation_id: str,
    user_id: int,
    user_message: str,
    mode: str,
    jd_id: int | None,
    resume_text: str | None,
    jd_text: str | None,
    model: str | None,
    bank_mode: str | None,
    difficulty: str | None = None,
    turn_id: str | None = None,
    turn_fence: int | None = None,
) -> ChatState:
    return {
        "conversation_id": conversation_id,
        "session_id": conversation_id,
        "user_id": user_id,
        "user_message": user_message,
        "turn_id": turn_id,
        "turn_fence": turn_fence,
        "mode": mode,
        "jd_id": jd_id,
        "jd_text": jd_text,
        "resume_text": resume_text,
        "model": model,
        "bank_mode": bank_mode or "all",
        "difficulty": difficulty or "mid",
        "interview_config": {},
        "interview_profile": None,
        "rhythm_profile": {},
        "memories": [],
        "memory_summaries": [],
        "resume_summary": None,
        "session_notes": "",
        "message_history": [],
        "compressed_context": None,
        "recent_messages": [],
        "budget_snapshot": None,
        "interview_context": "",
        "job_position": None,
        "intent": "interview_question",
        "keywords": [],
        "search_query": "",
        "retrieval_intent": None,
        "search_positive_terms": [],
        "search_negative_terms": [],
        "question_type": None,
        "answer_complete": False,
        "retrieved_questions": [],
        "candidate_questions": [],
        "selected_question": None,
        "question_source": None,
        "question_source_reason": None,
        "selected_basis_questions": [],
        "rerank_metadata": {},
        "response": "",
        "metadata": {},
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "active_skills": [],
        "tool_steps": [],
        "llm_usage_trace": [],
        "turn_contract": None,
        "turn_intent": None,
    }


# ═══════════════════════════════════════════════════
#  Pipeline Steps
# ═══════════════════════════════════════════════════


async def _step_load_context(state: ChatState) -> ChatState:
    """加载上下文：历史、记忆、简历、session notes"""
    _step("loading", "正在加载对话历史...", reason=STEP_REASONS["loading"])
    memory_result, history_result = await asyncio.gather(
        recall_memories(state),
        load_history(state),
    )
    state.update(memory_result)
    state.update(history_result)
    state["session_notes"] = chat_service.get_session_notes(state["conversation_id"])

    # 恢复上一轮持久化的 active skill names
    conversation_metadata = await asyncio.to_thread(
        chat_service.get_conversation_metadata,
        state["conversation_id"],
    )
    from app.agents.chat.nodes import _restore_active_skills_from_metadata

    _restore_active_skills_from_metadata(state, conversation_metadata)

    _step("context", "正在加载个人画像...", reason=STEP_REASONS["context"])
    interview_context, job_position = build_interview_context(
        state["user_id"], conversation_id=state["conversation_id"]
    )
    state["interview_context"] = interview_context
    state["job_position"] = job_position

    # 上下文压缩
    result = await summarize_context(state)
    state.update(result)

    # An incomplete frozen distribution plan has its own finite question target
    # and is measured from persisted events, not the 100-message LLM context.
    from app.agents.chat.distribution_runtime import distribution_plan_is_incomplete

    if not check_round_limit(
        state.get("message_history", []),
        allow_incomplete_distribution=distribution_plan_is_incomplete(state),
    ):
        raise RuntimeError("对话已达最大轮次限制（50轮），请新建对话继续")

    return state


async def _step_classify(state: ChatState) -> ChatState:
    """意图分类 + 关键词提取 + 记忆召回（单次 LLM 调用）"""
    recent = state.get("recent_messages", [])
    recent_context = ""
    if recent:
        recent_context = "\n".join(
            f"{'面试官' if m['role'] == 'assistant' else '候选人'}: {m['content'][:100]}"
            for m in recent[-4:]
        )

    is_first_message = len(state.get("message_history", [])) <= 1
    if is_first_message:
        _step(
            "understanding",
            "正在理解你的问题...",
            reason=STEP_REASONS["understanding_first"],
        )
    else:
        _step(
            "understanding",
            "正在分析你的回答...",
            reason=STEP_REASONS["understanding_follow"],
        )

    # The LLM semantic classifier owns the live routing decision on every
    # turn. Rule-based parsing is retained inside the classifier only for an
    # LLM-failure fallback, never as the normal first-turn path.
    (
        intent,
        memory_ids,
        keywords,
        search_query,
        answer_complete,
        structured_rewrite,
        classify_result,
    ) = await classify_and_recall(
        user_message=state["user_message"],
        recent_context=recent_context,
        memory_summaries=state.get("memory_summaries", []),
        user_id=state["user_id"],
    )

    state["intent"] = intent
    state["keywords"] = keywords
    state["search_query"] = search_query
    state["answer_complete"] = answer_complete

    # Spread structured classification fields into state.
    if classify_result:
        state["classify_result"] = classify_result
        for key in (
            "answer_quality",
            "should_retrieve",
            "transition_style",
            "escalation_level",
            "off_topic_streak",
            "repetition_streak",
            "requires_bank_question",
            "candidate_act",
            "counter_question",
            "asked_counter_question",
            "counter_question_topic",
            "asked_for_summary",
            "requested_end",
            "needs_clarification",
            "needs_new_dimension",
            "suggested_question_type",
            "confidence",
            "evidence",
        ):
            if key in classify_result:
                state[key] = classify_result[key]
        counter_evidence = classify_result.get("counter_question")
        state["counter_question_evidence"] = (
            counter_evidence if isinstance(counter_evidence, dict) else None
        )
        state["counter_question"] = bool(state["counter_question_evidence"])
        state["asked_counter_question"] = state["counter_question"]
        state["counter_question_topic"] = (
            state["counter_question_evidence"] or {}
        ).get("topic")

    # Compute reliable streak counters from message history and override LLM estimates.
    if not is_first_message:
        from app.agents.chat.question_plan import (
            _count_consecutive_similar_questions,
            _count_consecutive_similar_user_answers,
        )

        user_repeat = _count_consecutive_similar_user_answers(state)
        assistant_repeat, _ = _count_consecutive_similar_questions(state)
        state["repetition_streak"] = user_repeat
        # If the user is repeating, upgrade answer_quality and escalate.
        if user_repeat >= 1 and state.get("answer_quality") not in ("off_topic",):
            state["answer_quality"] = "repeated"
        # Assistant has pressed the same topic too many times.
        if assistant_repeat >= 2:
            state["escalation_level"] = max(state.get("escalation_level", 0), 2)

    if structured_rewrite:
        state["retrieval_intent"] = structured_rewrite.get("retrieval_intent")
        state["search_positive_terms"] = structured_rewrite.get("positive_terms", [])
        state["search_negative_terms"] = structured_rewrite.get("negative_terms", [])
        state["question_type"] = structured_rewrite.get("question_type")

    if memory_ids:
        full_memories = await asyncio.to_thread(
            chat_service.get_memories_by_ids, memory_ids, state["user_id"]
        )
        state["memory_summaries"] = [
            {
                "id": m["id"],
                "memory_type": m["memory_type"],
                "summary": m["content"][:80],
                "updated_at": m["created_at"],
            }
            for m in full_memories
        ]
    else:
        state["memory_summaries"] = chat_service.get_memory_summaries(
            state["user_id"], limit=3
        )

    if intent == "interview_question" and keywords:
        topic_tag = ", ".join(keywords[:3])
        pre_note = f"[pending] 候选人正在回答: {topic_tag}"
        current_notes = state.get("session_notes", "")
        state["session_notes"] = (
            f"{current_notes}\n{pre_note}" if current_notes else pre_note
        )

    logger.info(
        f"Pipeline classify: intent={intent}, keywords={keywords}, "
        f"search_query='{search_query}', answer_complete={answer_complete}"
    )
    return state


async def _step_extract_memory(state: ChatState) -> None:
    """Process the durable memory handoff without blocking the assistant turn."""
    try:
        assert_chat_turn_active(state)
        job = await asyncio.to_thread(
            chat_service.claim_side_effect_job,
            worker_id=f"chat-turn:{state.get('turn_id')}",
            kind="memory_extraction",
            source_turn_id=state.get("turn_id"),
        )
        if not job:
            return
        snapshot = dict(state)
        snapshot["_side_effect_job_id"] = job["id"]
        await extract_memory(snapshot)
    except chat_service.TurnCancelled:
        logger.info("跳过已取消回合的后台记忆提取: %s", state.get("turn_id"))
    except Exception as e:
        logger.debug(f"后台记忆提取失败（不影响主流程）: {e}")


async def _persist_active_skills(state: ChatState) -> None:
    """Persist only cross-turn skills to conversation metadata.

    Mode skills such as algorithm-coding/project-deep-dive are turn-scoped; if
    they are persisted, the next unrelated turn can inherit the wrong mode.
    """
    try:
        conversation_id = state.get("conversation_id")
        if not conversation_id:
            return
        assert_chat_turn_active(state)
        active_skills = [
            name
            for name in state.get("active_skills", [])
            if name in _PERSISTENT_SKILLS
        ]
        await asyncio.to_thread(
            chat_service.update_conversation_metadata,
            conversation_id,
            {
                "persistent_skill_names": active_skills,
                "active_skill_names": active_skills,
                "last_turn_skills": state.get("active_skills", []),
            },
        )
    except chat_service.TurnCancelled:
        raise
    except Exception:
        logger.exception("Failed to persist active_skills")


async def _persist_mcp_session(state: ChatState) -> None:
    """Persist MCP session state only while this turn still owns the fence."""
    assert_chat_turn_active(state)
    await save_mcp_session_async(
        state.get("session_id") or state["conversation_id"],
        state,
        user_id=state.get("user_id"),
    )


async def _load_interview_config(state: ChatState) -> None:
    """Load cross-turn interview config into ChatState."""

    metadata = await asyncio.to_thread(
        chat_service.get_conversation_metadata,
        state["conversation_id"],
    )
    config = metadata.get("interview_config") if isinstance(metadata, dict) else {}
    if not isinstance(config, dict):
        config = {}
    state["interview_config"] = config
    state["interview_profile"] = config.get("interview_profile")
    state["difficulty"] = config.get("difficulty") or state.get("difficulty") or "mid"
    distribution_plan = config.get("distribution_plan")
    state["distribution_plan"] = distribution_plan if isinstance(distribution_plan, dict) else None
    rhythm_profile = config.get("rhythm_profile")
    state["rhythm_profile"] = rhythm_profile if isinstance(rhythm_profile, dict) else {}


def _add_interview_observability_metadata(
    metadata: dict,
    state: ChatState,
    *,
    collected_steps: list[dict],
    collected_tool_steps: list[dict],
) -> dict:
    """Attach interview_state and observability summary to done metadata."""

    ledger = _build_interview_ledger(state)
    selected_question = state.get("selected_question")
    if selected_question:
        ledger.record_question(selected_question, state.get("question_type"))
    metadata["interview_state"] = build_interview_state_snapshot(
        state,
        ledger,
        state.get("rhythm_profile") or {},
    )
    if state.get("intent"):
        metadata["intent"] = state.get("intent")
    if isinstance(state.get("classify_result"), dict):
        metadata["classify_result"] = dict(state["classify_result"])
    if isinstance(state.get("turn_intent"), dict):
        metadata["turn_intent"] = dict(state["turn_intent"])
    public_active_skills = [
        name for name in state.get("active_skills", []) if name != "agent-interview"
    ]
    metadata["active_skills"] = public_active_skills
    observability = {
        "thinking_duration": metadata.get("thinking_duration", 0),
        "step_count": len(collected_steps),
        "active_skills": public_active_skills,
        "tool_step_count": len(collected_tool_steps or state.get("tool_steps", [])),
        "tool_trace_persisted": False,
    }
    stop_policy = _public_stop_policy_decision(state.get("interview_stop_decision"))
    if stop_policy:
        observability["stop_policy"] = stop_policy
    metadata["observability"] = observability
    return metadata


def _public_stop_policy_decision(decision: object) -> dict:
    """Return a compact JSON-safe stop-policy trace for done metadata."""

    if not isinstance(decision, dict):
        return {}
    public = {
        "action": decision.get("action"),
        "mode": decision.get("mode"),
        "reason": decision.get("reason"),
        "message_count": decision.get("message_count"),
        "missing_phases": decision.get("missing_phases", []),
    }
    coverage = decision.get("coverage")
    if isinstance(coverage, dict):
        public["coverage"] = {
            str(phase): {
                "current_count": data.get("current_count"),
                "threshold": data.get("threshold"),
                "is_covered": data.get("is_covered"),
            }
            for phase, data in coverage.items()
            if isinstance(data, dict)
        }
    return {key: value for key, value in public.items() if value is not None}


def _refresh_interview_state_snapshot(state: ChatState) -> None:
    """Refresh state['interview_state'] from the current ledger."""

    ledger = _build_interview_ledger(state)
    selected_question = state.get("selected_question")
    if selected_question:
        ledger.record_question(selected_question, state.get("question_type"))
    state["interview_state"] = build_interview_state_snapshot(
        state,
        ledger,
        state.get("rhythm_profile") or {},
    )


def _record_asked_question_if_any(state: ChatState, metadata: dict) -> None:
    """Record asked question to DB for cross-conversation dedup."""
    assert_chat_turn_active(state)
    if state.get("question_source") == "agent_internal":
        # Private catalog IDs are not question_bank IDs and should not be
        # written to the public interview history/dedup table.
        return
    selected = metadata.get("selected_question") or state.get("selected_question")
    if not selected or not isinstance(selected, dict):
        return
    qid = selected.get("id")
    if not qid:
        return
    try:
        from app.db.operations import get_db_connection, record_asked_question

        with get_db_connection() as conn:
            record_asked_question(
                conn,
                user_id=state.get("user_id"),
                conversation_id=state.get("conversation_id", ""),
                question_id=int(qid),
            )
    except Exception as e:
        logger.warning("Failed to record asked question %s: %s", qid, e)


def _attach_executed_contract_metadata(state: ChatState, metadata: dict) -> None:
    """Persist the contract that actually produced this turn's output."""
    turn_intent = state.get("turn_intent")
    if isinstance(turn_intent, dict):
        metadata["turn_intent"] = turn_intent
    contract = state.get("turn_contract")
    if isinstance(contract, dict):
        metadata["turn_contract"] = contract
        from app.agents.chat.structured_turn import (
            build_evidence_bundle,
            turn_contract_v2_from_legacy,
        )

        state["coverage_events"] = metadata.get("coverage_events", [])
        evidence = build_evidence_bundle(state)
        metadata["evidence_bundle"] = evidence.to_dict()
        metadata["turn_contract_v2"] = turn_contract_v2_from_legacy(
            contract,
            state=state,
            evidence=evidence,
        ).to_dict()
    if state.get("writer_trace"):
        metadata["writer_trace"] = state["writer_trace"]
    if state.get("validator_trace"):
        metadata["validator_trace"] = state["validator_trace"]
    if state.get("generation_error_code"):
        metadata["generation_error_code"] = state["generation_error_code"]
    selected = state.get("selected_question") or {}
    if selected.get("id"):
        metadata["tool_contract_trace"] = {
            "selected_question_id": selected["id"],
            "source": state.get("question_source") or "unknown",
        }


# ═══════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════


async def run_chat(
    conversation_id: str,
    user_id: int,
    user_message: str,
    mode: str = "free_practice",
    jd_id: int = None,
    resume_text: str = None,
    jd_text: str = None,
    model: str = None,
    bank_mode: str = None,
    difficulty: str = None,
    turn_id: str | None = None,
    turn_fence: int | None = None,
) -> AsyncGenerator[dict, None]:
    """面试对话 pipeline — SSE 兼容的 async generator。

    替代 LangGraph StateGraph，使用纯 async pipeline。
    所有事件通过 _event_queue_var 上下文变量传递。
    """
    queue: asyncio.Queue = asyncio.Queue()
    token = _event_queue_var.set(queue)

    state = _initial_state(
        conversation_id,
        user_id,
        user_message,
        mode,
        jd_id,
        resume_text,
        jd_text,
        model,
        bank_mode,
        difficulty,
        turn_id,
        turn_fence,
    )
    assert_chat_turn_active(state)

    async def _run_pipeline() -> None:
        t0 = time.monotonic()
        try:
            assert_chat_turn_active(state)
            # Load the frozen plan before context limits are evaluated, so a
            # long configured interview cannot be stopped by the LLM window.
            await _load_interview_config(state)
            # 1. 加载上下文
            await _step_load_context(state)
            assert_chat_turn_active(state)
            state["decision_config"] = get_decision_config(
                state.get("interview_config")
            )
            _refresh_interview_state_snapshot(state)

            # 2. 意图分类 + 关键词
            await _step_classify(state)
            assert_chat_turn_active(state)
            from app.agents.chat.distribution_runtime import apply_distribution_control

            apply_distribution_control(state)
            from app.agents.chat.turn_intent import build_turn_intent

            state["turn_intent"] = build_turn_intent(state).to_metadata_dict()

            # 3-5. ReAct 循环（替代 resolve_skills + route_and_generate）
            response = ""
            metadata = {}

            # Hard route: end_interview bypasses ReAct entirely — no tools
            # Phase 5: unified two-stage closing (closing_writer + summary_writer)
            if state.get("intent") == "end_interview":
                _emit(
                    {
                        "type": "step",
                        "step": "closing",
                        "message": "正在生成面试总结...",
                        "reason": STEP_REASONS["closing"],
                    }
                )
                from app.agents.chat.contract_executor import execute_turn_contract

                contract = plan_turn(state)
                state["turn_contract"] = contract.to_metadata_dict()
                close_result = await execute_turn_contract(
                    state=state,
                    contract=contract,
                    llm_call=lambda msgs: llm_service._call_llm_with_retry_messages(
                        msgs, user_id=state.get("user_id")
                    ),
                )
                state["writer_trace"] = close_result.get("writer_trace") or {}
                state["validator_trace"] = close_result.get("validator_trace") or []
                if close_result["status"] != "success":
                    state["generation_error_code"] = close_result.get("error_code")
                if close_result["status"] == "success":
                    response = close_result["text"]
                    _emit({"type": "chunk", "content": response})
                    built_metadata, clean_response = _build_react_metadata(state, response)
                    if built_metadata:
                        metadata = built_metadata
                    metadata["writer_trace"] = close_result["writer_trace"]
                    metadata["closing_stage"] = "closed"
                    metadata["has_summary"] = True
                    response = clean_response
                else:
                    metadata["writer_trace"] = close_result["writer_trace"]
                    _emit(
                        {
                            "type": "error",
                            "message": close_result["message"],
                            "code": close_result["error_code"],
                        }
                    )
                _attach_executed_contract_metadata(state, metadata)
                _record_asked_question_if_any(state, metadata)
                _emit({"type": "basis", **_basis_event_payload(metadata)})
                _emit({"type": "done", "metadata": metadata})
            else:
                async for event in _react_loop(state):
                    event_type = event.get("type")
                    if event_type == "done":
                        metadata = event.get("metadata", {})
                        built_metadata, clean_response = _build_react_metadata(
                            state, response
                        )
                        if built_metadata:
                            metadata = {**built_metadata, **metadata}
                        response = clean_response
                        _attach_executed_contract_metadata(state, metadata)
                        # Record asked question for cross-conversation dedup
                        _record_asked_question_if_any(state, metadata)
                        _emit({"type": "basis", **_basis_event_payload(metadata)})
                        _emit({"type": "done", "metadata": metadata})
                        continue
                    if event_type in {
                        "chunk",
                        "thinking",
                        "thinking_start",
                        "thinking_done",
                        "tool_step",
                        "error",
                    }:
                        if event_type == "chunk":
                            response += event.get("content", "")
                        _emit(event)
            state["response"] = response
            state["metadata"] = metadata

            # Persist/clear cross-turn skills so turn-scoped modes do not stick.
            await _persist_active_skills(state)
            await _persist_mcp_session(state)

            # 后台记忆提取
            assert_chat_turn_active(state)
            asyncio.create_task(_step_extract_memory(dict(state)))

            elapsed = time.monotonic() - t0
            logger.info(
                f"Pipeline completed in {elapsed:.1f}s, "
                f"intent={state.get('intent')}, "
                f"active_skills={state.get('active_skills', [])}"
            )
        except chat_service.TurnCancelled:
            logger.info("Pipeline stopped after turn cancellation: %s", state.get("turn_id"))
            queue.put_nowait({"type": "cancelled", "turn_id": state.get("turn_id")})
        except Exception as e:
            logger.exception("Pipeline 执行失败")
            queue.put_nowait({"type": "error", "message": _sanitize_error_message(e)})
        finally:
            queue.put_nowait(_SENTINEL)

    graph_task = asyncio.create_task(_run_pipeline())

    # Fix 4: accumulate step/thinking/insight events for metadata persistence
    run_started_at = time.monotonic()
    collected_steps: list[dict] = []
    collected_insights: list[dict] = []
    collected_thinking: list[dict] = []
    collected_tool_steps: list[dict] = []
    thinking_start_time: float | None = None

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break

            item_type = item.get("type")
            if item_type == "step":
                collected_steps.append(item)
            elif item_type == "tool_step":
                collected_tool_steps.append(item.get("data", {}))
                continue
            elif item_type == "insight":
                collected_insights.append(item)
            elif item_type == "thinking_start":
                thinking_start_time = time.monotonic()
                collected_thinking.append({"chunks": []})
            elif item_type == "thinking":
                if collected_thinking:
                    # 优先 content，fallback 到 data.text
                    chunk = item.get("content") or item.get("data", {}).get("text", "")
                    if chunk:
                        collected_thinking[-1].setdefault("chunks", []).append(chunk)
            elif item_type == "thinking_done":
                if collected_thinking:
                    duration = item.get("duration")
                    if duration is not None:
                        collected_thinking[-1]["duration_ms"] = int(
                            float(duration) * 1000
                        )
                    elif thinking_start_time:
                        collected_thinking[-1]["duration_ms"] = int(
                            (time.monotonic() - thinking_start_time) * 1000
                        )
                thinking_start_time = None
            elif item_type == "done":
                metadata = item.get("metadata", {})
                # Limit thinking chunks to avoid metadata bloat
                for t in collected_thinking:
                    chunks = t.get("chunks", [])
                    if len(chunks) > _MAX_THINKING_CHUNKS:
                        t["chunks"] = chunks[:_MAX_THINKING_CHUNKS]
                total_duration_ms = max(
                    int((time.monotonic() - run_started_at) * 1000),
                    sum(t.get("duration_ms", 0) for t in collected_thinking),
                )
                tool_trace = state.get("tool_calls_trace", [])
                skill_trace = state.get("skill_trace", [])
                if state.get("question_source") == "agent_internal":
                    skill_trace = [
                        item
                        for item in skill_trace
                        if item.get("skill_name") != "agent-interview"
                    ]
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
                metadata["thinking"] = collected_thinking
                metadata["thinking_duration"] = round(
                    reasoning_trace["duration_ms"] / 1000, 1
                )
                metadata["steps"] = collected_steps
                metadata["insights"] = collected_insights
                metadata["tool_steps"] = collected_tool_steps or state.get(
                    "tool_steps", []
                )
                usage_trace = state.get("llm_usage_trace", [])
                metadata["llm_usage"] = aggregate_cache_usage(
                    [
                        item.get("usage", {})
                        for item in usage_trace
                        if isinstance(item, dict)
                        and isinstance(item.get("usage"), dict)
                    ]
                )
                metadata = _add_interview_observability_metadata(
                    metadata,
                    state,
                    collected_steps=collected_steps,
                    collected_tool_steps=collected_tool_steps,
                )
                item = {**item, "metadata": metadata}

            yield item
            await asyncio.sleep(0)
    finally:
        _event_queue_var.reset(token)
        if not graph_task.done():
            graph_task.cancel()

"""Deterministic full-chain alignment: facts → stats → plan → controller → events."""

import json
import sqlite3

import pytest


def test_public_facts_default_plan_and_execution_remain_aligned(test_db):
    from app.agents.chat.distribution_controller import decide_next_question_type
    from app.agents.chat.distribution_execution import distribution_execution_from_events
    from app.services.interview_distribution import (
        compile_distribution_plan,
        get_distribution_default,
        refresh_distribution_scope,
    )

    interview_id = test_db.execute(
        """
        INSERT INTO interview (url, company, round, focus, questions_list, difficulty, owner_id, status, job_position)
        VALUES ('https://example.test/e2e', '', '', '', '', '', NULL, 'approved', 'Agent开发')
        """
    ).lastrowid
    facts = ["project_followup", "knowledge_probe", "knowledge_probe", "algorithm_coding", "system_design", "behavioral"]
    for index, question_type in enumerate(facts):
        test_db.execute(
            """
            INSERT INTO questions_detail (interview_id, url, question, question_type, dimension, job_position)
            VALUES (?, 'https://example.test/e2e', ?, ?, 'knowledge_probe', 'Agent开发')
            """,
            (interview_id, f"Q{index}", question_type),
        )

    stats = refresh_distribution_scope(test_db, "public_job_position", "Agent开发")
    default = get_distribution_default(test_db, "Agent开发")
    plan = compile_distribution_plan(test_db, user_id=1, job_position="Agent开发", request_override={
        "mode": "system_default", "target_question_count": 10,
    }, preference=None)

    events = []
    for _ in range(plan["target_question_count"]):
        decision = decide_next_question_type(plan, events, {})
        assert decision.preferred_type in decision.allowed_types
        events.append({
            "plan_id": plan["plan_id"], "question_type": decision.preferred_type,
            "counts_toward_target": True, "selection_reason": decision.selection_reason,
        })
    execution = distribution_execution_from_events(plan, events)

    assert default["raw_counts"] == stats["raw_counts"]
    assert plan["stats_version"] == default["stats_version"]
    assert plan["distribution"] == default["distribution"]
    assert execution["status"] == "completed"
    assert execution["actual_counts"] == plan["soft_target_counts"]


def test_active_distribution_plan_forces_the_next_primary_question_to_its_controller_type():
    """A live plan is a backend control, not prompt-only guidance."""
    from app.agents.chat.distribution_runtime import apply_distribution_control

    plan = {
        "plan_id": "runtime-plan",
        "random_seed": "seed",
        "target_question_count": 3,
        "soft_target_counts": {
            "project_followup": 0,
            "knowledge_probe": 1,
            "algorithm_coding": 1,
            "system_design": 1,
            "behavioral": 0,
        },
        "allowed_counts": {
            name: {"min": 0, "max": 3}
            for name in (
                "project_followup",
                "knowledge_probe",
                "algorithm_coding",
                "system_design",
                "behavioral",
            )
        },
    }
    state = {
        "distribution_plan": plan,
        "message_history": [
            {"role": "assistant", "content": "opening"},
            {"role": "user", "content": "intro"},
            {"role": "assistant", "content": "followup"},
            {"role": "user", "content": "complete answer"},
        ],
        "answer_quality": "complete",
        "classify_result": {"answer_quality": "complete"},
        "intent": "interview_question",
    }

    control = apply_distribution_control(state)

    assert control["enforce_primary_question"] is True
    assert control["preferred_type"] in {"knowledge_probe", "algorithm_coding", "system_design"}
    assert state["distribution_primary_required"] is True
    assert state["strategy_preferred_question_type"] == control["preferred_type"]
    assert state["question_type"] == control["preferred_type"]
    assert state["requires_bank_question"] is True
    assert state["needs_new_dimension"] is True


def test_unbound_conversation_followup_is_not_counted_against_an_active_distribution_plan():
    from app.agents.chat.metadata import _build_react_metadata

    plan = {
        "plan_id": "runtime-plan",
        "soft_target_counts": {
            "project_followup": 0,
            "knowledge_probe": 1,
            "algorithm_coding": 1,
            "system_design": 1,
            "behavioral": 0,
        },
    }
    state = {
        "interview_config": {"distribution_plan": plan},
        "distribution_plan": plan,
        "question_source": "conversation",
        "question_source_reason": "retrieval_recommended_but_skipped",
        "question_type": "project_followup",
        "interview_state": {"current_phase": "project_followup"},
        "retrieved_questions": [],
        "candidate_questions": [],
    }

    metadata, _ = _build_react_metadata(state, "请介绍一下这个项目最难的取舍是什么？")

    event = metadata["coverage_events"][0]
    assert event["plan_id"] == "runtime-plan"
    assert event["question_type"] == "project_followup"
    assert event["counts_toward_target"] is False
    assert event["selection_reason"] == "unbound_conversation_followup"


def test_bank_question_without_a_controller_decision_is_not_counted_against_an_active_distribution_plan():
    from app.agents.chat.metadata import _build_react_metadata

    plan = {
        "plan_id": "runtime-plan",
        "soft_target_counts": {
            "project_followup": 0,
            "knowledge_probe": 1,
            "algorithm_coding": 1,
            "system_design": 1,
            "behavioral": 0,
        },
    }
    state = {
        "interview_config": {"distribution_plan": plan},
        "distribution_plan": plan,
        "question_source": "draw",
        "question_source_reason": "question_plan_bound",
        "question_type": "new_question",
        "selected_question": {
            "id": 99,
            "question": "如何对 Agent 的产出做评估？",
            "tags": "Agent",
        },
        "next_question_plan": {"must_ask": True, "question_id": 99},
        "question_plan_metadata": {"adherence": {"adheres": True}},
        "retrieved_questions": [],
        "candidate_questions": [],
    }

    metadata, _ = _build_react_metadata(state, "如何对 Agent 的产出做评估？")

    event = metadata["coverage_events"][0]
    assert event["counts_toward_target"] is False
    assert event["selection_reason"] == "unbound_conversation_followup"


def test_explicit_practice_request_is_eligible_for_distribution_control_even_when_classifier_marks_answer_vague():
    from app.agents.chat.distribution_runtime import apply_distribution_control

    plan = {
        "plan_id": "runtime-plan",
        "random_seed": "seed",
        "target_question_count": 1,
        "soft_target_counts": {
            "project_followup": 0,
            "knowledge_probe": 1,
            "algorithm_coding": 0,
            "system_design": 0,
            "behavioral": 0,
        },
        "allowed_counts": {
            name: {"min": 0, "max": 1}
            for name in (
                "project_followup",
                "knowledge_probe",
                "algorithm_coding",
                "system_design",
                "behavioral",
            )
        },
    }
    state = {
        "distribution_plan": plan,
        "message_history": [{"role": "user", "content": "x"}] * 4,
        "intent": "practice_request",
        "answer_quality": "vague",
        "classify_result": {"answer_quality": "vague"},
    }

    control = apply_distribution_control(state)

    assert control["enforce_primary_question"] is True
    assert control["preferred_type"] == "knowledge_probe"


@pytest.mark.parametrize(
    "request_text",
    (
        "请继续下一题，从题库中出一道技术题。",
        "请基于题库继续下一道技术题。",
        "不要结束面试，继续出下一道技术题。",
    ),
)
def test_explicit_next_question_request_overrides_a_false_classifier_end_signal_while_plan_is_incomplete(request_text):
    from app.agents.chat.distribution_runtime import apply_distribution_control

    plan = {
        "plan_id": "runtime-plan",
        "random_seed": "seed",
        "target_question_count": 1,
        "soft_target_counts": {
            "project_followup": 0,
            "knowledge_probe": 1,
            "algorithm_coding": 0,
            "system_design": 0,
            "behavioral": 0,
        },
        "allowed_counts": {
            name: {"min": 0, "max": 1}
            for name in (
                "project_followup",
                "knowledge_probe",
                "algorithm_coding",
                "system_design",
                "behavioral",
            )
        },
    }
    state = {
        "distribution_plan": plan,
        "message_history": [{"role": "user", "content": "x"}] * 4,
        "user_message": request_text,
        "intent": "end_interview",
        "counter_question": True,
        "answer_quality": "complete",
        "classify_result": {
            "answer_quality": "complete",
            "requested_end": True,
            "counter_question": {"topic": "技术面试题"},
        },
    }

    control = apply_distribution_control(state)

    assert control["enforce_primary_question"] is True
    assert state["intent"] == "practice_request"
    assert state["classify_result"]["requested_end"] is False
    assert state["counter_question"] is False
    assert state["classify_result"]["counter_question"] is None


def test_negated_next_question_request_does_not_override_a_real_end_signal():
    from app.agents.chat.distribution_runtime import apply_distribution_control

    plan = {
        "plan_id": "runtime-plan",
        "target_question_count": 1,
        "soft_target_counts": {
            "project_followup": 0,
            "knowledge_probe": 1,
            "algorithm_coding": 0,
            "system_design": 0,
            "behavioral": 0,
        },
        "allowed_counts": {
            name: {"min": 0, "max": 1}
            for name in (
                "project_followup",
                "knowledge_probe",
                "algorithm_coding",
                "system_design",
                "behavioral",
            )
        },
    }
    state = {
        "distribution_plan": plan,
        "message_history": [{"role": "user", "content": "x"}] * 4,
        "user_message": "不要继续下一道技术题，我想结束面试。",
        "intent": "end_interview",
        "answer_quality": "complete",
        "classify_result": {"answer_quality": "complete", "requested_end": True},
    }

    control = apply_distribution_control(state)

    assert control["enforce_primary_question"] is False
    assert control["reason"] == "turn_not_eligible_for_primary_question"
    assert state["intent"] == "end_interview"
    assert state["classify_result"]["requested_end"] is True


@pytest.mark.asyncio
async def test_distribution_control_draws_and_binds_a_typed_question_without_waiting_for_llm_tool_use(monkeypatch):
    from app.agents.chat import react_loop

    state = {
        "intent": "interview_question",
        "question_type": "system_design",
        "strategy_preferred_question_type": "system_design",
        "distribution_primary_required": True,
        "distribution_control": {"preferred_type": "system_design"},
        "requires_bank_question": True,
        "message_history": [
            {"role": "assistant", "content": "opening"},
            {"role": "user", "content": "intro"},
            {"role": "assistant", "content": "followup"},
            {"role": "user", "content": "complete answer"},
        ],
        "candidate_questions": [],
        "retrieved_questions": [],
        "search_negative_terms": [],
    }
    calls = []

    async def fake_execute_tool(tool_call, target_state):
        calls.append(json.loads(tool_call["function"]["arguments"]))
        candidate = {
            "id": 42,
            "question": "请设计一个支持限流、降级和多活容灾的高并发服务。",
            "cat1": "系统设计",
            "cat2": "高可用架构",
            "tags": "系统设计,高可用",
        }
        target_state["candidate_questions"] = [candidate]
        target_state["retrieved_questions"] = [candidate]
        target_state["question_source"] = "draw"
        target_state["question_source_reason"] = "draw_questions returned candidate questions"
        return json.dumps({"ok": True, "items": [candidate], "metadata": {}})

    monkeypatch.setattr(react_loop.chat_tools, "execute_tool", fake_execute_tool)

    prepared = await react_loop._prepare_distribution_primary_question(state)

    assert prepared is True
    assert calls == [{"count": 5, "question_type": "system_design"}]
    assert state["selected_question"]["id"] == 42
    assert state["next_question_plan"]["must_ask"] is True


@pytest.mark.asyncio
async def test_distribution_control_retries_with_cross_conversation_reuse_after_pool_exhaustion(monkeypatch):
    from app.agents.chat import react_loop

    state = {
        "intent": "practice_request",
        "question_type": "algorithm_coding",
        "strategy_preferred_question_type": "algorithm_coding",
        "distribution_primary_required": True,
        "distribution_control": {"preferred_type": "algorithm_coding"},
        "requires_bank_question": True,
        "message_history": [{"role": "user", "content": "answer"}] * 4,
        "candidate_questions": [],
        "retrieved_questions": [],
        "search_negative_terms": [],
    }
    calls = []

    async def fake_execute_tool(tool_call, target_state):
        calls.append(target_state.get("distribution_allow_cross_conversation_reuse", False))
        if len(calls) == 1:
            target_state["candidate_questions"] = []
            target_state["retrieved_questions"] = []
            return json.dumps({"ok": True, "items": [], "metadata": {"empty_reason": "no_match"}})
        candidate = {
            "id": 7,
            "question": "给定数组，如何在 O(n) 时间内找到两数之和？",
            "cat1": "算法",
            "cat2": "数组",
            "tags": "算法,代码",
        }
        target_state["candidate_questions"] = [candidate]
        target_state["retrieved_questions"] = [candidate]
        target_state["question_source"] = "draw"
        target_state["question_source_reason"] = "draw_questions returned candidate questions"
        return json.dumps({"ok": True, "items": [candidate], "metadata": {}})

    monkeypatch.setattr(react_loop.chat_tools, "execute_tool", fake_execute_tool)

    prepared = await react_loop._prepare_distribution_primary_question(state)

    assert prepared is True
    assert calls == [False, True]
    assert state["selected_question"]["id"] == 7


def test_draw_tool_contract_accepts_behavioral_distribution_type():
    from app.agents.chat.tool_gateway import DrawQuestionsInput

    assert DrawQuestionsInput(question_type="behavioral").question_type == "behavioral"


def test_behavioral_draw_filter_includes_collaboration_signals_used_by_distribution_mapping():
    from app.services.question_draw_service import _question_type_filter

    _condition, params = _question_type_filter("behavioral")

    assert "%协作%" in params
    assert "%冲突%" in params
    assert "%失败%" in params
    assert "%star%" in params
    assert "%影响力%" in params
    assert "%职业规划%" in params


def test_behavioral_hr_signal_requires_a_standalone_acronym_in_classifier_and_draw_filter():
    from app.services.interview_distribution import QuestionType, map_question_type
    from app.services.question_draw_service import _question_type_filter

    assert map_question_type("", "", "操作系统", "How does the thread scheduler work?") == QuestionType.KNOWLEDGE_PROBE
    assert map_question_type("", "", "HR", "请做自我介绍。") == QuestionType.BEHAVIORAL

    condition, params = _question_type_filter("behavioral")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE question_bank (cat1 TEXT, cat2 TEXT, tags TEXT, question TEXT)")
    conn.executemany(
        "INSERT INTO question_bank VALUES (?, ?, ?, ?)",
        [
            ("基础", "操作系统", "调度", "How does the thread scheduler work?"),
            ("HR", "", "", "请做自我介绍。"),
        ],
    )

    rows = conn.execute(
        f"SELECT question FROM question_bank qb WHERE {condition}", params
    ).fetchall()

    assert rows == [("请做自我介绍。",)]


@pytest.mark.asyncio
async def test_pipeline_keeps_incomplete_long_distribution_plan_running_after_context_window(monkeypatch):
    from app.agents.chat import pipeline
    from app.services import chat_service

    plan = {
        "plan_id": "long-plan",
        "target_question_count": 50,
        "soft_target_counts": {
            "project_followup": 0,
            "knowledge_probe": 50,
            "algorithm_coding": 0,
            "system_design": 0,
            "behavioral": 0,
        },
    }

    async def fake_recall(_state):
        return {"memory_summaries": [], "resume_summary": None}

    async def fake_history(_state):
        return {"message_history": [{"role": "assistant", "content": "old"}] * 100}

    async def fake_summarize(_state):
        return {"recent_messages": [], "compressed_context": None, "budget_snapshot": None}

    monkeypatch.setattr(pipeline, "recall_memories", fake_recall)
    monkeypatch.setattr(pipeline, "load_history", fake_history)
    monkeypatch.setattr(pipeline, "summarize_context", fake_summarize)
    monkeypatch.setattr(pipeline, "build_interview_context", lambda *_args, **_kwargs: ("", "Agent开发"))
    monkeypatch.setattr(pipeline.chat_service, "get_session_notes", lambda _conversation_id: "")
    monkeypatch.setattr(pipeline.chat_service, "get_conversation_metadata", lambda _conversation_id: {})
    monkeypatch.setattr(
        chat_service,
        "get_distribution_events",
        lambda _conversation_id: [
            {"plan_id": "long-plan", "question_type": "knowledge_probe", "counts_toward_target": True}
        ] * 49,
    )
    state = {"conversation_id": "long-conversation", "user_id": 1, "distribution_plan": plan}

    await pipeline._step_load_context(state)

    assert len(state["message_history"]) == 100


def test_stop_policy_defers_generic_transcript_cap_while_distribution_primary_is_required():
    from app.agents.chat.stop_policy import evaluate_interview_stop

    decision = evaluate_interview_stop(
        {
            "message_history": [{"role": "assistant", "content": "old"}] * 100,
            "distribution_primary_required": True,
            "closing_stage": "technical",
        }
    )

    assert decision["action"] == "continue"
    assert decision["reason"] == "distribution_plan_incomplete"


def test_distribution_primary_supersedes_generic_candidate_question_wrap_up():
    from app.agents.chat.turn_contract import TurnContractAction, plan_turn

    state = {
        "closing_stage": "candidate_question_asked",
        "distribution_primary_required": True,
        "intent": "interview_question",
        "classify_result": {
            "answer_quality": "complete",
            "needs_new_dimension": True,
            "confidence": 1.0,
        },
        "selected_question": {
            "id": 11,
            "question": "请设计一个支持多租户限流的服务。",
            "cat1": "系统设计",
        },
        "selection_confidence": 1.0,
        "question_source": "draw",
    }

    contract = plan_turn(state)

    assert contract.action == TurnContractAction.ASK_SELECTED_QUESTION


def test_distribution_event_reader_uses_persisted_events_instead_of_bounded_chat_history(monkeypatch):
    from app.agents.chat.distribution_runtime import distribution_events_from_history
    from app.services import chat_service

    persisted_events = [
        {"plan_id": "plan-1", "question_type": "behavioral", "counts_toward_target": True}
    ]
    monkeypatch.setattr(chat_service, "get_distribution_events", lambda _conversation_id: persisted_events)
    state = {
        "conversation_id": "conversation-1",
        "message_history": [{"role": "assistant", "metadata": {}}] * 100,
    }

    assert distribution_events_from_history(state, "plan-1") == persisted_events

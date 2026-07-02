"""Stop-policy tests for natural interview wrap-up."""

from __future__ import annotations

from app.agents.chat.coverage_config import InterviewPhase


def _question_message(qid: int, phase: str) -> dict:
    return {
        "role": "assistant",
        "content": f"Question {qid} for {phase}",
        "metadata": {
            "selected_question": {
                "id": qid,
                "question": f"Question {qid} for {phase}",
                "tags": phase,
            }
        },
    }


def _coverage_event_message(qid: int, phase: str) -> dict:
    return {
        "role": "assistant",
        "content": f"Conversation-only question {qid} for {phase}",
        "metadata": {
            "coverage_events": [
                {
                    "phase": phase,
                    "source": "conversation",
                    "confidence": "medium",
                    "question_text": f"Conversation-only question {qid} for {phase}",
                }
            ]
        },
    }


def _covered_history(message_count: int = 33) -> list[dict]:
    phases = (
        [InterviewPhase.PROJECT_FOLLOWUP.value] * 6
        + [InterviewPhase.KNOWLEDGE_PROBE.value] * 3
        + [InterviewPhase.ALGORITHM_CODING.value]
        + [InterviewPhase.SYSTEM_DESIGN.value]
        + [InterviewPhase.BEHAVIORAL.value]
    )
    messages: list[dict] = []
    for idx, phase in enumerate(phases, start=1):
        messages.append(_question_message(idx, phase))
        messages.append({"role": "user", "content": f"answer {idx}"})
    extra_idx = 0
    _extra_answers = [
        "Redis 我用在缓存层，设了合理 TTL 避免雪崩。",
        "MySQL 索引用 B+ 树，查询走覆盖索引优化。",
        "TCP 三次握手是 SYN、SYN-ACK、ACK 三步。",
        "进程是资源分配单位，线程是调度单位，共享地址空间。",
        "B+ 树叶子节点串链表，范围查询效率高。",
        "哈希表 O(1) 查找，冲突用链地址法解决。",
        "跳表是有序链表加多层索引，平均 O(logN)。",
        "堆排序建大顶堆，逐个取堆顶，时间 O(NlogN)。",
    ]
    while len(messages) < message_count:
        answer = _extra_answers[extra_idx % len(_extra_answers)]
        extra_idx += 1
        messages.append({"role": "user", "content": answer})
    return messages[:message_count]


def _covered_event_history(message_count: int = 33) -> list[dict]:
    phases = (
        [InterviewPhase.PROJECT_FOLLOWUP.value] * 6
        + [InterviewPhase.KNOWLEDGE_PROBE.value] * 3
        + [InterviewPhase.ALGORITHM_CODING.value]
        + [InterviewPhase.SYSTEM_DESIGN.value]
        + [InterviewPhase.BEHAVIORAL.value]
    )
    messages: list[dict] = []
    for idx, phase in enumerate(phases, start=1):
        messages.append(_coverage_event_message(idx, phase))
        messages.append({"role": "user", "content": f"answer {idx}"})
    extra_idx = 0
    _extra_answers = [
        "Redis 我用在缓存层，设了合理 TTL 避免雪崩。",
        "MySQL 索引用 B+ 树，查询走覆盖索引优化。",
        "TCP 三次握手是 SYN、SYN-ACK、ACK 三步。",
        "进程是资源分配单位，线程是调度单位，共享地址空间。",
    ]
    while len(messages) < message_count:
        answer = _extra_answers[extra_idx % len(_extra_answers)]
        extra_idx += 1
        messages.append({"role": "user", "content": answer})
    return messages[:message_count]


def _base_state(message_history: list[dict]) -> dict:
    return {
        "conversation_id": "conv-stop-policy",
        "job_position": "agent_llm",
        "difficulty": "senior",
        "message_history": message_history,
        "user_message": "继续",
    }


def test_soft_close_does_not_stop_when_coverage_incomplete():
    from app.agents.chat.stop_policy import evaluate_interview_stop

    state = _base_state([_question_message(1, "project_followup")] * 33)

    decision = evaluate_interview_stop(state)

    assert decision["action"] == "continue"
    assert decision["mode"] == "active"
    assert "knowledge_probe" in decision["missing_phases"]


def test_soft_close_asks_candidate_question_when_coverage_complete():
    from app.agents.chat.stop_policy import evaluate_interview_stop

    state = _base_state(_covered_history(33))

    decision = evaluate_interview_stop(state)

    assert decision["action"] == "ask_candidate_question"
    assert decision["reason"] == "coverage_complete_ready_for_candidate_question"
    assert "你有什么想问" in decision["message"]


def test_soft_close_uses_persisted_coverage_events_at_api_entry():
    from app.agents.chat.stop_policy import evaluate_interview_stop

    state = _base_state(_covered_event_history(33))

    decision = evaluate_interview_stop(state)

    assert decision["action"] == "ask_candidate_question"
    assert decision["missing_phases"] == []
    assert decision["coverage"]["knowledge_probe"]["current_count"] == 3
    assert decision["coverage"]["behavioral"]["current_count"] == 1


def test_soft_close_finishes_after_candidate_question_round():
    from app.agents.chat.stop_policy import evaluate_interview_stop

    history = _covered_history(34)
    history.append({"role": "assistant", "content": "你有什么想问我们的吗？"})
    state = _base_state(history)
    state["user_message"] = "没有了，谢谢"

    decision = evaluate_interview_stop(state)

    assert decision["action"] == "close"
    assert decision["reason"] == "coverage_complete_after_candidate_question"


def test_strong_close_mode_only_allows_gap_fill_or_wrap_up():
    from app.agents.chat.stop_policy import evaluate_interview_stop

    history = _covered_history(45)
    # Remove the system-design signal while keeping the conversation long.
    for msg in history:
        selected = (msg.get("metadata") or {}).get("selected_question")
        if selected and selected.get("tags") == "system_design":
            selected["tags"] = "project_followup"
            selected["question"] = "Project follow-up instead"
            break
    state = _base_state(history)

    decision = evaluate_interview_stop(state)

    assert decision["action"] == "continue"
    assert decision["mode"] == "strong_close"
    assert decision["missing_phases"] == ["system_design"]


def test_hard_stop_closes_even_when_coverage_incomplete():
    from app.agents.chat.stop_policy import evaluate_interview_stop

    state = _base_state([_question_message(1, "project_followup")] * 57)

    decision = evaluate_interview_stop(state)

    assert decision["action"] == "close"
    assert decision["reason"] == "hard_stop_by_message_count"

"""P1 durable side effects and P2 structured turn contracts."""

from datetime import datetime, timedelta

import pytest

from app.services import chat_service


def _conversation():
    return chat_service.create_conversation(1, "free_practice", job_position="agent_llm")


def _completed_turn(conversation_id: str):
    turn = chat_service.reserve_chat_turn(
        conversation_id,
        1,
        "p1-request",
        "我负责过 Redis 缓存和 RAG 系统的稳定性建设。",
    )
    chat_service.finalize_chat_turn(
        turn.id,
        turn.fence,
        conversation_id,
        1,
        "请详细说明你如何处理缓存一致性？",
        {"coverage_events": [{"phase": "knowledge_probe", "counts_toward_target": True}]},
    )
    return turn


def test_finalize_enqueues_idempotent_memory_job_and_generation(test_db):
    conversation = _conversation()
    turn = _completed_turn(conversation["id"])

    job = chat_service.get_side_effect_job(
        test_db.execute("SELECT id FROM chat_side_effect_jobs LIMIT 1").fetchone()[0]
    )
    assert job["kind"] == "memory_extraction"
    assert job["source_turn_id"] == turn.id
    generation = chat_service.get_current_assistant_generation(conversation["id"], 1)
    assert generation["message_id"] == chat_service.get_chat_turn(turn.id)["assistant_message_id"]
    events = chat_service.get_interview_events(conversation["id"], 1)
    assert events[0]["event_type"] == "coverage"


def test_memory_job_is_retryable_and_deduplicates_provenance(test_db):
    conversation = _conversation()
    turn = _completed_turn(conversation["id"])
    job_id = test_db.execute("SELECT id FROM chat_side_effect_jobs LIMIT 1").fetchone()[0]
    job = chat_service.claim_side_effect_job(worker_id="test", source_turn_id=turn.id)
    assert job["id"] == job_id

    result = chat_service.commit_memory_extraction_job(
        job_id,
        [{"type": "weakness", "content": "Redis 一致性边界需要继续练习"}],
        ["[weakness] Redis 一致性边界需要继续练习"],
    )
    assert result["memory_count"] == 1
    assert chat_service.get_memories(1)[0]["content"] == "Redis 一致性边界需要继续练习"
    assert chat_service.get_session_notes(conversation["id"]).startswith("[weakness]")

    # A second job retry cannot create a duplicate memory.
    duplicate_job = chat_service.claim_side_effect_job(worker_id="test", source_turn_id=turn.id)
    assert duplicate_job is None


def test_versioned_metadata_and_session_notes_reject_stale_writer(test_db):
    conversation = _conversation()
    conv_id = conversation["id"]
    metadata_snapshot = chat_service.get_conversation_metadata_snapshot(conv_id)
    notes_snapshot = chat_service.get_session_notes_snapshot(conv_id)
    assert chat_service.update_conversation_metadata(
        conv_id, {"one": 1}, expected_version=metadata_snapshot["version"]
    ) == 1
    assert chat_service.update_session_notes(
        conv_id, "[topics] Redis", expected_version=notes_snapshot["version"]
    ) == 1
    with pytest.raises(chat_service.SideEffectConflict):
        chat_service.update_conversation_metadata(
            conv_id, {"stale": True}, expected_version=metadata_snapshot["version"]
        )
    with pytest.raises(chat_service.SideEffectConflict):
        chat_service.update_session_notes(
            conv_id, "stale", expected_version=notes_snapshot["version"]
        )


def test_expired_memory_is_not_returned(test_db):
    chat_service.save_memory(
        1,
        "weakness",
        "expired memory",
        expires_at=(datetime.utcnow() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    assert chat_service.get_memories(1) == []


def test_candidate_set_consumption_reloads_authoritative_question(test_db):
    conversation = _conversation()
    test_db.execute(
        "INSERT INTO question_bank (question, cat1, cat2, tags, status) "
        "VALUES ('如何保证缓存一致性？', '后端', 'Redis', 'knowledge_probe', 'approved')"
    )
    question_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    test_db.commit()
    candidate_set_id = chat_service.create_candidate_set(
        user_id=1,
        conversation_id=conversation["id"],
        source="search",
        items=[{"id": question_id}],
        source_turn_id=None,
        expires_at=(datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    resolved = chat_service.resolve_candidate_question(
        candidate_set_id,
        user_id=1,
        conversation_id=conversation["id"],
        selected_item_id=question_id,
    )
    assert resolved["question"] == "如何保证缓存一致性？"
    with pytest.raises(ValueError):
        chat_service.consume_candidate_set(
            candidate_set_id,
            user_id=1,
            conversation_id=conversation["id"],
            selected_item_id=question_id,
        )


def test_evidence_bundle_and_contract_v2_are_hashed_and_typed():
    from app.agents.chat.structured_turn import (
        EvidenceBundle,
        build_evidence_bundle,
        turn_contract_v2_from_legacy,
        validate_writer_output,
    )

    state = {
        "turn_id": "turn-1",
        "question_source": "draw",
        "selected_question": {"id": 7},
        "coverage_events": [
            {"phase": "knowledge_probe", "counts_toward_target": True, "confidence": "high"}
        ],
    }
    evidence = build_evidence_bundle(state)
    assert isinstance(evidence, EvidenceBundle)
    contract = turn_contract_v2_from_legacy(
        {"action": "ask_selected_question", "payload": {"question_id": 7}, "validation": ["non_empty"]},
        state=state,
        evidence=evidence,
    )
    assert len(contract.contract_hash) == 64
    assert validate_writer_output("你如何保证缓存一致性？", contract)["valid"]
    assert not validate_writer_output("thought: internal", contract)["valid"]


def test_event_fold_rejects_illegal_lifecycle_transition():
    folded = chat_service.fold_interview_events(
        [
            {"turn_id": "t1", "event_type": "state_transition", "payload": {"to": "closed"}},
            {"turn_id": "t2", "event_type": "state_transition", "payload": {"to": "technical"}},
        ]
    )
    assert folded["state"] == "closed"

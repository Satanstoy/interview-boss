"""Recorded replay, Golden Trace and Shadow Eval contracts."""

import asyncio

import pytest

from app.services import chat_service


def _turn():
    conversation = chat_service.create_conversation(1, "free_practice", job_position="agent_llm")
    turn = chat_service.reserve_chat_turn(
        conversation["id"],
        1,
        "replay-request",
        "我负责过一个高并发系统。",
        harness_version="2.0",
    )
    return conversation, turn


def _record_call(conversation, turn):
    action = chat_service.create_harness_action(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_key="observe",
        action_type="observe_propose",
        phase="observe_propose",
    )
    attempt = chat_service.start_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=action["id"],
        call_mode="observe_propose",
        provider="test-provider",
        model="test-model",
        context_pack_hash="ctx-hash",
        request_hash="request-hash",
        sampling_hash="sampling-hash",
        skill_hashes=["skill-v1-hash"],
    )
    manifest = {
        "harness_version": "2.0",
        "prompt_schema": "agent-result-v1",
        "stable_prefix_hash": "stable-hash",
        "context_pack_hash": "ctx-hash",
        "skill_hashes": ["skill-v1-hash"],
        "provider": "test-provider",
        "model": "test-model",
        "sampling_hash": "sampling-hash",
        "request_hash": "request-hash",
    }
    chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=action["id"],
        attempt_id=attempt["id"],
        artifact_type="context_manifest",
        content=manifest,
        visibility="audit",
    )
    chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=action["id"],
        attempt_id=attempt["id"],
        artifact_type="provider_response",
        content={"payload": {"intent": "answer"}},
        visibility="audit",
    )
    chat_service.finish_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        attempt_id=attempt["id"],
        status="succeeded",
        output={"payload": {"intent": "answer"}},
    )
    return manifest


def test_recorded_replay_reads_immutable_provider_artifacts_without_model_call(test_db):
    from app.services.harness_replay_service import recorded_replay

    conversation, turn = _turn()
    manifest = _record_call(conversation, turn)

    replay = recorded_replay(
        turn_id=turn.id,
        user_id=1,
        conversation_id=conversation["id"],
        expected_manifest=manifest,
    )

    assert replay["replayable"] is True
    assert replay["snapshot_incomplete"] is True
    assert replay["mismatches"] == []
    assert replay["calls"][0]["provider_response"]["payload"]["intent"] == "answer"
    assert [event["type"] for event in replay["events"]] == [
        "turn.started",
        "turn.queued",
    ]


def test_recorded_replay_marks_identity_mismatch_and_user_scope_hides_audit(test_db):
    from app.services.harness_replay_service import list_harness_artifacts, recorded_replay

    conversation, turn = _turn()
    manifest = _record_call(conversation, turn)
    user_artifacts = list_harness_artifacts(
        turn_id=turn.id, user_id=1, conversation_id=conversation["id"], scope="user"
    )
    assert user_artifacts == []
    chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        artifact_type="provider_request",
        content={"prompt": "model-only"},
        visibility="model",
    )
    model_artifacts = list_harness_artifacts(
        turn_id=turn.id,
        user_id=1,
        conversation_id=conversation["id"],
        scope="model",
        audit_authorized=True,
    )
    assert [item["artifact_type"] for item in model_artifacts] == ["provider_request"]

    replay = recorded_replay(
        turn_id=turn.id,
        user_id=1,
        conversation_id=conversation["id"],
        expected_manifest={**manifest, "model": "different-model"},
    )
    assert replay["replayable"] is False
    assert any(item["field"] == "model" for item in replay["mismatches"])


def test_sensitive_artifact_visibility_cannot_be_user(test_db):
    conversation, turn = _turn()

    with pytest.raises(ValueError, match="visibility"):
        chat_service.append_harness_artifact(
            user_id=1,
            conversation_id=conversation["id"],
            turn_id=turn.id,
            artifact_type="provider_response",
            content={"secret": True},
            visibility="user",
        )


def test_production_sensitive_artifact_encryption_fails_closed(test_db, monkeypatch):
    conversation, turn = _turn()
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("HARNESS_ALLOW_PLAINTEXT_ARTIFACTS", raising=False)

    def unavailable(_value):
        raise RuntimeError("key unavailable")

    monkeypatch.setattr("app.services.encryption.encrypt_value", unavailable)

    with pytest.raises(RuntimeError, match="require encryption"):
        chat_service.append_harness_artifact(
            user_id=1,
            conversation_id=conversation["id"],
            turn_id=turn.id,
            artifact_type="provider_response",
            content={"secret": True},
            visibility="audit",
        )


def test_legacy_turn_is_not_presented_as_harness_2_replay(test_db):
    from app.services.harness_replay_service import recorded_replay

    conversation = chat_service.create_conversation(1, "free_practice", job_position="agent_llm")
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "legacy-replay", "旧路径消息", harness_version=None
    )

    replay = recorded_replay(
        turn_id=turn.id,
        user_id=1,
        conversation_id=conversation["id"],
    )

    assert replay["replayable"] is False
    assert replay["manifest"]["harness_version"] != "2.0"
    assert any(item["code"] == "LEGACY_PROVENANCE" for item in replay["mismatches"])


def test_recorded_replay_detects_attempt_provenance_drift(test_db):
    from app.services.harness_replay_service import recorded_replay

    conversation, turn = _turn()
    manifest = _record_call(conversation, turn)
    test_db.execute(
        "UPDATE interview_attempts SET model = ? WHERE turn_id = ?",
        ("different-model", turn.id),
    )
    test_db.commit()

    replay = recorded_replay(
        turn_id=turn.id,
        user_id=1,
        conversation_id=conversation["id"],
        expected_manifest=manifest,
    )

    assert replay["replayable"] is False
    assert any(
        item["field"] == "model" and item["source"] == "attempt"
        for item in replay["mismatches"]
    )


def test_recorded_replay_matches_each_attempt_to_its_own_manifest(test_db):
    from app.services.harness_replay_service import recorded_replay

    conversation, turn = _turn()
    first_manifest = _record_call(conversation, turn)
    second_action = chat_service.create_harness_action(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_key="write-response",
        action_type="write_response",
        phase="write_response",
    )
    second_manifest = {
        **first_manifest,
        "context_pack_hash": "ctx-write",
        "request_hash": "request-write",
    }
    second_attempt = chat_service.start_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=second_action["id"],
        call_mode="write_response",
        provider="test-provider",
        model="test-model",
        context_pack_hash="ctx-write",
        request_hash="request-write",
        sampling_hash="sampling-hash",
        skill_hashes=["skill-v1-hash"],
    )
    chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=second_action["id"],
        attempt_id=second_attempt["id"],
        artifact_type="context_manifest",
        content=second_manifest,
        visibility="audit",
    )
    chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=second_action["id"],
        attempt_id=second_attempt["id"],
        artifact_type="provider_response",
        content={"payload": {"display_text": "继续"}},
        visibility="audit",
    )
    chat_service.finish_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        attempt_id=second_attempt["id"],
        status="succeeded",
        output={"payload": {"display_text": "继续"}},
    )

    replay = recorded_replay(
        turn_id=turn.id,
        user_id=1,
        conversation_id=conversation["id"],
    )

    assert replay["replayable"] is True
    assert replay["mismatches"] == []
    assert [call["context_pack_hash"] for call in replay["calls"]] == [
        "ctx-hash",
        "ctx-write",
    ]


def test_golden_trace_and_shadow_eval_are_read_only(test_db):
    from app.services.harness_replay_service import (
        GOLDEN_TRACE_SCENARIOS,
        load_golden_trace_contract,
        recorded_replay,
        run_shadow_eval,
        validate_golden_trace,
    )

    conversation, turn = _turn()
    manifest = _record_call(conversation, turn)
    replay = recorded_replay(
        turn_id=turn.id,
        user_id=1,
        conversation_id=conversation["id"],
        expected_manifest=manifest,
    )
    before = chat_service.get_interview_ledger(conversation["id"], user_id=1)
    trace = validate_golden_trace(replay, {"scenario": "normal"})
    async def judge(value):
        value["calls"].clear()
        return {"score": 0.9}

    shadow = asyncio.run(run_shadow_eval(replay, judge))
    after = chat_service.get_interview_ledger(conversation["id"], user_id=1)

    assert trace["passed"] is True
    assert set(GOLDEN_TRACE_SCENARIOS) == {
        "normal",
        "incomplete_answer",
        "off_topic",
        "refusal",
        "skip_question",
        "end_interview",
        "multilingual",
        "question_bank_empty",
        "provider_timeout",
        "schema_error",
        "prompt_injection",
        "edit_revision",
        "sse_recovery",
    }
    prompt_injection_contract = load_golden_trace_contract("prompt_injection")
    assert prompt_injection_contract["harness"] == "interview-harness@2.0"
    assert "prompt_boundary" in prompt_injection_contract["hard_gates"]
    assert shadow["read_only"] is True
    assert shadow["judge"]["score"] == 0.9
    assert len(replay["calls"]) == 1
    assert before == after

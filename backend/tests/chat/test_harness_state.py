"""Durable Session/Ledger/TurnRun state for Harness 2.0."""

from app.db.connection import get_db_connection
from app.services import chat_service


def _conversation():
    return chat_service.create_conversation(
        user_id=1,
        mode="free_practice",
        job_position="agent_llm",
    )


def test_harness_state_schema_and_session_ledger_bootstrap(test_db):
    conversation = _conversation()

    with get_db_connection() as conn:
        conversation_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(chat_conversations)").fetchall()
        }
        turn_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(chat_turns)").fetchall()
        }
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        session = conn.execute(
            "SELECT harness_version, session_version FROM chat_conversations WHERE id = ?",
            (conversation["id"],),
        ).fetchone()
        ledger = conn.execute(
            "SELECT conversation_id, ledger_version, current_phase "
            "FROM interview_ledgers WHERE conversation_id = ?",
            (conversation["id"],),
        ).fetchone()

    assert {"harness_version", "session_version", "interview_config_json"} <= conversation_columns
    assert {
        "harness_status",
        "terminal_reason",
        "session_version",
        "ledger_version_at_start",
        "turn_run_version",
        "current_action_id",
        "current_attempt_no",
        "latest_sequence",
        "budget_snapshot_json",
        "context_pack_hash",
        "revision_of_turn_id",
    } <= turn_columns
    assert {"interview_ledgers", "interview_actions", "interview_attempts", "interview_artifacts"} <= tables
    assert session["harness_version"] == "2.0"
    assert session["session_version"] == 1
    assert ledger["conversation_id"] == conversation["id"]
    assert ledger["ledger_version"] == 1
    assert ledger["current_phase"] == "opening"


def test_reserve_turn_copies_session_and_ledger_versions(test_db):
    conversation = _conversation()
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-state-1", "请介绍一下你做过的项目"
    )

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT harness_status, session_version, ledger_version_at_start, "
            "turn_run_version, current_attempt_no, latest_sequence, "
            "budget_snapshot_json, context_pack_hash, started_at "
            "FROM chat_turns WHERE id = ?",
            (turn.id,),
        ).fetchone()

    assert row["harness_status"] == "running"
    assert row["session_version"] == 1
    assert row["ledger_version_at_start"] == 1
    assert row["turn_run_version"] == 1
    assert row["current_attempt_no"] == 0
    assert row["latest_sequence"] == 0
    assert row["budget_snapshot_json"] == "{}"
    assert row["context_pack_hash"] == ""
    assert row["started_at"] is not None


def test_turn_context_snapshot_is_updated_without_rebuilding_the_turn(test_db):
    conversation = _conversation()
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-state-context", "请继续追问"
    )

    snapshot = chat_service.persist_turn_context_snapshot(
        turn.id,
        turn.fence,
        conversation["id"],
        1,
        context_pack_hash="stable-hash-1",
        budget_snapshot={"available_tokens": 1200},
    )

    assert snapshot["context_pack_hash"] == "stable-hash-1"
    assert snapshot["budget_snapshot"] == {"available_tokens": 1200}
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT context_pack_hash, budget_snapshot_json, turn_run_version "
            "FROM chat_turns WHERE id = ?",
            (turn.id,),
        ).fetchone()
    assert row["context_pack_hash"] == "stable-hash-1"
    assert row["budget_snapshot_json"] == '{"available_tokens":1200}'
    assert row["turn_run_version"] == 2


def test_turn_base_context_snapshot_is_frozen_and_recoverable(test_db):
    from app.agents.chat.harness_contract import ContextBlock, build_context_pack

    conversation = _conversation()
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-frozen-base", "本轮固定输入"
    )
    pack = build_context_pack(
        stable_prefix=[
            ContextBlock("stable", "system_rules", "harness", {"v": 1}, "model", 0)
        ],
        turn_base=[
            ContextBlock("input", "candidate_input", "user", {"text": "本轮固定输入"}, "model", 0)
        ],
        call_suffix=[],
    )
    first = chat_service.persist_turn_context_snapshot(
        turn.id,
        turn.fence,
        conversation["id"],
        1,
        context_pack_hash=pack.context_pack_hash,
        stable_prefix_hash=pack.stable_prefix_hash,
        budget_snapshot={"available_tokens": 900},
        context_base_snapshot={
            "stable_prefix": [item.as_dict() for item in pack.stable_prefix],
            "turn_base": [item.as_dict() for item in pack.turn_base],
        },
    )
    second = chat_service.persist_turn_context_snapshot(
        turn.id,
        turn.fence,
        conversation["id"],
        1,
        context_pack_hash=pack.context_pack_hash,
        stable_prefix_hash=pack.stable_prefix_hash,
        budget_snapshot={"available_tokens": 1},
        context_base_snapshot={"turn_base": [{"content": "不能覆盖"}]},
    )
    frozen = chat_service.get_frozen_turn_context_base(
        turn.id, user_id=1, conversation_id=conversation["id"]
    )

    assert first["context_base_snapshot"]["turn_base"][0]["content"]["text"] == "本轮固定输入"
    assert second["context_base_snapshot"] == first["context_base_snapshot"]
    assert frozen == first["context_base_snapshot"]


def test_revision_points_to_original_turn_without_overwriting_it(test_db):
    conversation = _conversation()
    original = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-state-original", "原始回答"
    )
    assistant_id = chat_service.finalize_chat_turn(
        original.id,
        original.fence,
        conversation["id"],
        1,
        "原始面试官回复",
        {},
    )

    revision, _ = chat_service.reserve_chat_revision(
        conversation["id"], 1, assistant_id, "harness-state-revision"
    )

    with get_db_connection() as conn:
        original_row = conn.execute(
            "SELECT harness_status, revision_of_turn_id FROM chat_turns WHERE id = ?",
            (original.id,),
        ).fetchone()
        revision_row = conn.execute(
            "SELECT harness_status, revision_of_turn_id FROM chat_turns WHERE id = ?",
            (revision.id,),
        ).fetchone()

    assert original_row["harness_status"] == "completed"
    assert original_row["revision_of_turn_id"] is None
    assert revision_row["harness_status"] == "running"
    assert revision_row["revision_of_turn_id"] == original.id


def test_edit_creates_new_user_message_and_preserves_source_turn(test_db):
    conversation = _conversation()
    original = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-edit-original", "原始候选人回答"
    )
    chat_service.finalize_chat_turn(
        original.id,
        original.fence,
        conversation["id"],
        1,
        "原始面试官追问",
        {},
    )

    edited = chat_service.reserve_chat_edit_revision(
        conversation["id"],
        1,
        original.id,
        "修订后的候选人回答",
        "harness-edit-new",
    )

    assert edited.id != original.id
    assert edited.user_message_id != original.user_message_id
    assert edited.revision_of_turn_id == original.id
    messages = chat_service.get_messages(conversation["id"])
    assert [message["content"] for message in messages] == [
        "原始候选人回答",
        "原始面试官追问",
        "修订后的候选人回答",
    ]

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT revision_of_turn_id, harness_status FROM chat_turns WHERE id = ?",
            (edited.id,),
        ).fetchone()
    assert row["revision_of_turn_id"] == original.id
    assert row["harness_status"] == "running"


def test_finalize_optimistically_commits_authoritative_ledger(test_db):
    conversation = _conversation()
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-ledger-commit", "我负责 Redis 缓存优化"
    )
    chat_service.finalize_chat_turn(
        turn.id,
        turn.fence,
        conversation["id"],
        1,
        "继续说说缓存击穿的处理。",
        {
            "selected_question": {"id": 42, "question": "缓存击穿怎么处理？", "cat1": "中间件", "cat2": "缓存"},
            "coverage_events": [{"question_id": 42, "phase": "knowledge_probe"}],
            "interview_state": {"current_phase": "knowledge_probe", "coverage": {"knowledge_probe": {"current_count": 1}}},
        },
    )

    ledger = chat_service.get_interview_ledger(conversation["id"], user_id=1)
    assert ledger["ledger_version"] == 2
    assert ledger["asked_question_refs"][0]["id"] == 42
    assert ledger["coverage_events"][0]["question_id"] == 42
    assert ledger["current_phase"] == "knowledge_probe"

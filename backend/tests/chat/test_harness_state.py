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

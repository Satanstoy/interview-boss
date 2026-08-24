"""Durable Harness 2.0 Session/Ledger helpers.

This module owns the small amount of state needed to bootstrap and read the
authoritative interview ledger.  Turn execution still lives in
``chat_turn_service``; the split keeps the four core objects from leaking into
the legacy chat facade.
"""

import json
import hashlib
import uuid

from app.db.connection import get_db_connection
from app.services.chat_common import _safe_json_loads


def ensure_interview_ledger_conn(conn, *, user_id: int, conversation_id: str) -> str:
    """Create the one ledger snapshot for a session, if it is missing."""
    ledger_id = f"ledger:{conversation_id}"
    conn.execute(
        """
        INSERT OR IGNORE INTO interview_ledgers
            (id, user_id, conversation_id)
        VALUES (?, ?, ?)
        """,
        (ledger_id, int(user_id), conversation_id),
    )
    return ledger_id


def get_interview_ledger(
    conversation_id: str,
    *,
    user_id: int | None = None,
) -> dict | None:
    """Return the authoritative ledger snapshot, never a prompt-derived copy."""
    where = ["conversation_id = ?"]
    params: list[object] = [conversation_id]
    if user_id is not None:
        where.append("user_id = ?")
        params.append(int(user_id))
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM interview_ledgers WHERE " + " AND ".join(where),
            params,
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    for key in (
        "asked_question_refs_json",
        "coverage_events_json",
        "covered_dimensions_json",
        "recent_rhythm_signals_json",
    ):
        result[key.removesuffix("_json")] = _safe_json_loads(result[key])
        if key.endswith("_json") and key in result:
            del result[key]
    return result


def get_harness_session(conversation_id: str, *, user_id: int | None = None) -> dict | None:
    """Read the explicit Session snapshot used to freeze a TurnRun base."""
    where = ["id = ?"]
    params: list[object] = [conversation_id]
    if user_id is not None:
        where.append("user_id = ?")
        params.append(int(user_id))
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, status, mode, harness_version, session_version, "
            "language, question_strategy, interview_config_json, provider_policy_json "
            "FROM chat_conversations WHERE " + " AND ".join(where),
            params,
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    for field in ("interview_config_json", "provider_policy_json"):
        try:
            parsed = json.loads(result[field] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        result[field.removesuffix("_json")] = parsed if isinstance(parsed, dict) else {}
        del result[field]
    return result


def persist_turn_context_snapshot(
    turn_id: str,
    fence: int,
    conversation_id: str,
    user_id: int,
    *,
    context_pack_hash: str,
    budget_snapshot: dict,
) -> dict:
    """Freeze the Turn Base hash and budget exactly once per active turn."""
    encoded_budget = json.dumps(
        budget_snapshot or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = conn.execute(
                "UPDATE chat_turns SET context_pack_hash = ?, budget_snapshot_json = ?, "
                "turn_run_version = turn_run_version + 1 "
                "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ? "
                "AND status = 'running'",
                (
                    str(context_pack_hash or ""),
                    encoded_budget,
                    turn_id,
                    fence,
                    conversation_id,
                    user_id,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("turn is not active or does not belong to the caller")
            row = conn.execute(
                "SELECT context_pack_hash, budget_snapshot_json, turn_run_version "
                "FROM chat_turns WHERE id = ?",
                (turn_id,),
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "context_pack_hash": row["context_pack_hash"],
        "budget_snapshot": json.loads(row["budget_snapshot_json"] or "{}"),
        "turn_run_version": int(row["turn_run_version"]),
    }


def create_action_conn(
    conn,
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    action_key: str,
    action_type: str,
    phase: str,
    input_payload: dict | None = None,
) -> dict:
    """Create or replay one semantic Action by its TurnRun-local key."""
    existing = conn.execute(
        "SELECT * FROM interview_actions WHERE turn_id = ? AND action_key = ?",
        (turn_id, action_key),
    ).fetchone()
    if existing:
        return dict(existing)
    action_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO interview_actions
            (id, user_id, conversation_id, turn_id, action_key, action_type,
             phase, input_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action_id,
            int(user_id),
            conversation_id,
            turn_id,
            action_key,
            action_type,
            phase,
            json.dumps(input_payload or {}, ensure_ascii=False, sort_keys=True),
        ),
    )
    return dict(
        conn.execute(
            "SELECT * FROM interview_actions WHERE id = ?", (action_id,)
        ).fetchone()
    )


def create_harness_action(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    action_key: str,
    action_type: str,
    phase: str,
    input_payload: dict | None = None,
) -> dict:
    """Create or replay an Action with a stable TurnRun-local identity."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            owned = conn.execute(
                "SELECT id FROM chat_turns WHERE id = ? AND conversation_id = ? AND user_id = ?",
                (turn_id, conversation_id, user_id),
            ).fetchone()
            if not owned:
                raise ValueError("turn does not belong to the caller")
            action = create_action_conn(
                conn,
                user_id=user_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                action_key=action_key,
                action_type=action_type,
                phase=phase,
                input_payload=input_payload,
            )
            conn.commit()
            return action
        except Exception:
            conn.rollback()
            raise


def start_harness_attempt(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    action_id: str,
    call_mode: str,
    provider: str = "",
    model: str = "",
    context_pack_hash: str = "",
    prompt_cache_key: str = "",
    request_hash: str = "",
) -> dict:
    """Start a new provider attempt; retry never overwrites the old attempt."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            action = conn.execute(
                "SELECT id FROM interview_actions "
                "WHERE id = ? AND turn_id = ? AND conversation_id = ? AND user_id = ?",
                (action_id, turn_id, conversation_id, user_id),
            ).fetchone()
            if not action:
                raise ValueError("action does not belong to the caller")
            current = conn.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) AS attempt_no "
                "FROM interview_attempts WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            attempt_no = int(current["attempt_no"] or 0) + 1
            conn.execute(
                "UPDATE interview_attempts SET status = 'superseded', finished_at = CURRENT_TIMESTAMP "
                "WHERE action_id = ? AND status = 'active'",
                (action_id,),
            )
            attempt_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO interview_attempts
                    (id, user_id, conversation_id, turn_id, action_id, attempt_no,
                     call_mode, provider, model, context_pack_hash, prompt_cache_key,
                     request_hash, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    attempt_id,
                    user_id,
                    conversation_id,
                    turn_id,
                    action_id,
                    attempt_no,
                    call_mode,
                    provider,
                    model,
                    context_pack_hash,
                    prompt_cache_key,
                    request_hash,
                ),
            )
            conn.execute(
                "UPDATE interview_actions SET status = 'started', current_attempt_no = ?, "
                "started_at = COALESCE(started_at, CURRENT_TIMESTAMP) WHERE id = ?",
                (attempt_no, action_id),
            )
            conn.execute(
                "UPDATE chat_turns SET current_action_id = ?, current_attempt_no = ? "
                "WHERE id = ? AND conversation_id = ? AND user_id = ?",
                (action_id, attempt_no, turn_id, conversation_id, user_id),
            )
            row = conn.execute(
                "SELECT * FROM interview_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            conn.commit()
            return dict(row)
        except Exception:
            conn.rollback()
            raise


def append_harness_artifact(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    artifact_type: str,
    content: object,
    visibility: str = "audit",
    action_id: str | None = None,
    attempt_id: str | None = None,
) -> dict:
    """Append one immutable prompt/reasoning/tool/output artifact."""
    if visibility not in {"user", "audit", "model"}:
        raise ValueError("invalid artifact visibility")
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    artifact_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            owned = conn.execute(
                "SELECT id FROM chat_turns WHERE id = ? AND conversation_id = ? AND user_id = ?",
                (turn_id, conversation_id, user_id),
            ).fetchone()
            if not owned:
                raise ValueError("turn does not belong to the caller")
            conn.execute(
                """
                INSERT INTO interview_artifacts
                    (id, user_id, conversation_id, turn_id, action_id, attempt_id,
                     artifact_type, visibility, content_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    user_id,
                    conversation_id,
                    turn_id,
                    action_id,
                    attempt_id,
                    artifact_type,
                    visibility,
                    canonical,
                    content_hash,
                ),
            )
            row = conn.execute(
                "SELECT * FROM interview_artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            conn.commit()
            return dict(row)
        except Exception:
            conn.rollback()
            raise

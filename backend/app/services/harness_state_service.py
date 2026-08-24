"""Durable Harness 2.0 Session/Ledger helpers.

This module owns the small amount of state needed to bootstrap and read the
authoritative interview ledger.  Turn execution still lives in
``chat_turn_service``; the split keeps the four core objects from leaking into
the legacy chat facade.
"""

import json
import hashlib
import uuid
import logging

from app.db.connection import get_db_connection
from app.services.chat_common import SideEffectConflict

logger = logging.getLogger("interview-boss")


def _assert_lease_conn(conn, turn_id: str, lease_owner: str | None = None) -> None:
    """Fence worker-owned mutations after a lease takeover."""
    if lease_owner is None:
        return
    row = conn.execute(
        "SELECT lease_owner FROM chat_turns WHERE id = ?",
        (turn_id,),
    ).fetchone()
    if not row or row["lease_owner"] != str(lease_owner):
        from app.services.chat_event_service import TurnEventLeaseLost

        raise TurnEventLeaseLost(turn_id)


def _json_value(raw, fallback):
    """Parse a JSON column while preserving list/object shape."""
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


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
        fallback = [] if key.endswith(("refs_json", "events_json", "signals_json")) else {}
        parsed = _json_value(result[key], fallback)
        result[key.removesuffix("_json")] = parsed if isinstance(parsed, type(fallback)) else fallback
        if key.endswith("_json") and key in result:
            del result[key]
    return result


def _ledger_projection(metadata: dict, current: dict) -> dict:
    """Translate completed-turn metadata into the durable Ledger shape."""
    snapshot = metadata.get("interview_state") if isinstance(metadata, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    selected = metadata.get("selected_question") if isinstance(metadata, dict) else {}
    selected = selected if isinstance(selected, dict) else {}

    asked = list(current.get("asked_question_refs") or [])
    refs = metadata.get("asked_question_refs") if isinstance(metadata, dict) else None
    refs = refs if isinstance(refs, list) else []
    if selected.get("id"):
        refs.append({
            "id": selected.get("id"),
            "question": selected.get("question", ""),
            "cat1": selected.get("cat1", ""),
            "cat2": selected.get("cat2", ""),
        })
    seen = {str(item.get("id")) for item in asked if isinstance(item, dict) and item.get("id")}
    for item in refs:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id")) if item.get("id") else json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            asked.append(item)
            seen.add(key)

    coverage = list(current.get("coverage_events") or [])
    new_coverage = metadata.get("coverage_events") if isinstance(metadata, dict) else None
    for event in new_coverage if isinstance(new_coverage, list) else []:
        if event not in coverage:
            coverage.append(event)

    dimensions = snapshot.get("coverage")
    if not isinstance(dimensions, dict):
        dimensions = current.get("covered_dimensions") or {}
    topic = selected.get("cat2") or selected.get("cat1") or current.get("current_topic") or ""
    return {
        "asked_question_refs": asked,
        "coverage_events": coverage,
        "covered_dimensions": dimensions,
        "current_topic": topic,
        "current_phase": snapshot.get("current_phase") or current.get("current_phase") or "opening",
        "depth": int(metadata.get("depth") or current.get("depth") or 0),
        "closing_stage": metadata.get("closing_stage") or current.get("closing_stage") or "technical",
        "counter_question_status": metadata.get("counter_question_status") or current.get("counter_question_status") or "not_started",
        "recent_rhythm_signals": metadata.get("recent_rhythm_signals") or current.get("recent_rhythm_signals") or [],
    }


def commit_interview_ledger_conn(
    conn,
    *,
    turn_id: str,
    fence: int,
    conversation_id: str,
    user_id: int,
    metadata: dict | None,
) -> dict:
    """Optimistically commit one completed turn into the authoritative Ledger."""
    turn = conn.execute(
        "SELECT status, ledger_version_at_start FROM chat_turns "
        "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ?",
        (turn_id, fence, conversation_id, user_id),
    ).fetchone()
    if not turn:
        raise ValueError("turn is not owned by the caller")
    expected = int(turn["ledger_version_at_start"] or 1)
    ledger = conn.execute(
        "SELECT * FROM interview_ledgers WHERE conversation_id = ? AND user_id = ?",
        (conversation_id, user_id),
    ).fetchone()
    if not ledger:
        raise ValueError("interview ledger not found")
    if int(ledger["ledger_version"] or 1) != expected:
        raise SideEffectConflict("interview_ledger", int(ledger["ledger_version"] or 1))
    current = dict(ledger)
    for field in (
        "asked_question_refs",
        "coverage_events",
        "covered_dimensions",
        "recent_rhythm_signals",
    ):
        current[field] = _json_value(current.get(f"{field}_json"), [] if field.endswith(("refs", "events", "signals")) else {})
    projected = _ledger_projection(metadata or {}, current)
    updated = conn.execute(
        "UPDATE interview_ledgers SET asked_question_refs_json = ?, coverage_events_json = ?, "
        "covered_dimensions_json = ?, current_topic = ?, current_phase = ?, depth = ?, "
        "closing_stage = ?, counter_question_status = ?, recent_rhythm_signals_json = ?, "
        "ledger_version = ledger_version + 1, updated_at = CURRENT_TIMESTAMP "
        "WHERE conversation_id = ? AND user_id = ? AND ledger_version = ?",
        (
            json.dumps(projected["asked_question_refs"], ensure_ascii=False, sort_keys=True),
            json.dumps(projected["coverage_events"], ensure_ascii=False, sort_keys=True),
            json.dumps(projected["covered_dimensions"], ensure_ascii=False, sort_keys=True),
            projected["current_topic"],
            projected["current_phase"],
            projected["depth"],
            projected["closing_stage"],
            projected["counter_question_status"],
            json.dumps(projected["recent_rhythm_signals"], ensure_ascii=False, sort_keys=True),
            conversation_id,
            user_id,
            expected,
        ),
    )
    if updated.rowcount != 1:
        current_version = conn.execute(
            "SELECT ledger_version FROM interview_ledgers WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        raise SideEffectConflict("interview_ledger", int(current_version["ledger_version"]))
    conn.execute(
        "UPDATE chat_turns SET turn_run_version = turn_run_version + 1 WHERE id = ?",
        (turn_id,),
    )
    return {
        **projected,
        "ledger_version": expected + 1,
    }


def commit_interview_ledger(
    *,
    turn_id: str,
    fence: int,
    conversation_id: str,
    user_id: int,
    metadata: dict | None,
) -> dict:
    """Commit a Ledger update in its own transaction for service callers/tests."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = commit_interview_ledger_conn(
                conn,
                turn_id=turn_id,
                fence=fence,
                conversation_id=conversation_id,
                user_id=user_id,
                metadata=metadata,
            )
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise


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
    stable_prefix_hash: str = "",
    budget_snapshot: dict,
    lease_owner: str | None = None,
) -> dict:
    """Freeze the Turn Base hash and budget exactly once per active turn."""
    if not isinstance(budget_snapshot, dict):
        if hasattr(budget_snapshot, "__dict__"):
            budget_snapshot = dict(vars(budget_snapshot))
        else:
            budget_snapshot = {}
    encoded_budget = json.dumps(
        budget_snapshot or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT context_pack_hash, stable_prefix_hash, budget_snapshot_json, "
                "turn_run_version, lease_owner FROM chat_turns "
                "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ? "
                "AND status = 'running'",
                (turn_id, fence, conversation_id, user_id),
            ).fetchone()
            if not existing:
                raise ValueError("turn is not active or does not belong to the caller")
            if lease_owner is not None and existing["lease_owner"] != str(lease_owner):
                _assert_lease_conn(conn, turn_id, lease_owner)
            if existing["context_pack_hash"]:
                if (
                    existing["context_pack_hash"] != str(context_pack_hash or "")
                    or existing["stable_prefix_hash"] != str(stable_prefix_hash or "")
                ):
                    raise ValueError("Turn Base ContextPack is already frozen")
                conn.commit()
                return {
                    "context_pack_hash": existing["context_pack_hash"],
                    "stable_prefix_hash": existing["stable_prefix_hash"],
                    "budget_snapshot": json.loads(existing["budget_snapshot_json"] or "{}"),
                    "turn_run_version": int(existing["turn_run_version"]),
                }
            updated = conn.execute(
                "UPDATE chat_turns SET context_pack_hash = ?, stable_prefix_hash = ?, "
                "budget_snapshot_json = ?, "
                "turn_run_version = turn_run_version + 1 "
                "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ? "
                "AND status = 'running' "
                + ("AND lease_owner = ?" if lease_owner is not None else ""),
                (
                    str(context_pack_hash or ""),
                    str(stable_prefix_hash or ""),
                    encoded_budget,
                    turn_id,
                    fence,
                    conversation_id,
                    user_id,
                    *((str(lease_owner),) if lease_owner is not None else ()),
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("turn is not active or does not belong to the caller")
            row = conn.execute(
                "SELECT context_pack_hash, stable_prefix_hash, budget_snapshot_json, turn_run_version "
                "FROM chat_turns WHERE id = ?",
                (turn_id,),
            ).fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "context_pack_hash": row["context_pack_hash"],
        "stable_prefix_hash": row["stable_prefix_hash"],
        "budget_snapshot": json.loads(row["budget_snapshot_json"] or "{}"),
        "turn_run_version": int(row["turn_run_version"]),
    }


def claim_harness_turn(
    turn_id: str,
    *,
    lease_owner: str,
    lease_seconds: int = 90,
) -> bool:
    """Acquire the database lease that makes a worker execution recoverable."""
    safe_lease = max(15, min(int(lease_seconds), 3600))
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = conn.execute(
                "UPDATE chat_turns SET lease_owner = ?, "
                "lease_expires_at = datetime('now', ?), heartbeat_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'running' AND "
                "(lease_owner IS NULL OR lease_expires_at IS NULL "
                "OR lease_expires_at <= CURRENT_TIMESTAMP OR lease_owner = ?)",
                (str(lease_owner), f"+{safe_lease} seconds", turn_id, str(lease_owner)),
            )
            conn.commit()
            return updated.rowcount == 1
        except Exception:
            conn.rollback()
            raise


def heartbeat_harness_turn(turn_id: str, *, lease_owner: str, lease_seconds: int = 90) -> bool:
    """Extend a live worker lease without changing any business state."""
    safe_lease = max(15, min(int(lease_seconds), 3600))
    with get_db_connection() as conn:
        updated = conn.execute(
            "UPDATE chat_turns SET lease_expires_at = datetime('now', ?), "
            "heartbeat_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'running' "
            "AND lease_owner = ?",
            (f"+{safe_lease} seconds", turn_id, str(lease_owner)),
        )
        conn.commit()
    return updated.rowcount == 1


def release_harness_turn_lease(turn_id: str, *, lease_owner: str) -> bool:
    """Release only the lease owned by this worker."""
    with get_db_connection() as conn:
        updated = conn.execute(
            "UPDATE chat_turns SET lease_owner = NULL, lease_expires_at = NULL "
            "WHERE id = ? AND lease_owner = ?",
            (turn_id, str(lease_owner)),
        )
        conn.commit()
    return updated.rowcount == 1


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
    lease_owner: str | None = None,
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
            _assert_lease_conn(conn, turn_id, lease_owner)
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
    lease_owner: str | None = None,
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
            _assert_lease_conn(conn, turn_id, lease_owner)
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


def get_completed_harness_attempt(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    action_id: str,
    call_mode: str | None = None,
    model: str | None = None,
    context_pack_hash: str | None = None,
    request_hash: str | None = None,
) -> dict | None:
    """Return a succeeded provider result so a recovered worker can skip it."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT a.id AS attempt_id, a.attempt_no, ar.content_json "
            "FROM interview_attempts a "
            "JOIN interview_artifacts ar ON ar.attempt_id = a.id "
            "WHERE a.id IN (SELECT id FROM interview_attempts WHERE action_id = ? "
            "AND status = 'succeeded') "
            "AND a.turn_id = ? AND a.conversation_id = ? AND a.user_id = ? "
            + ("AND a.call_mode = ? " if call_mode is not None else "")
            + ("AND a.model = ? " if model is not None else "")
            + ("AND a.context_pack_hash = ? " if context_pack_hash is not None else "")
            + ("AND a.request_hash = ? " if request_hash is not None else "")
            + "AND ar.artifact_type = 'provider_response' "
            + "ORDER BY a.attempt_no DESC LIMIT 1",
            (
                action_id,
                turn_id,
                conversation_id,
                user_id,
                *((call_mode,) if call_mode is not None else ()),
                *((model,) if model is not None else ()),
                *((context_pack_hash,) if context_pack_hash is not None else ()),
                *((request_hash,) if request_hash is not None else ()),
            ),
        ).fetchone()
    if not row:
        return None
    raw = row["content_json"] or "{}"
    try:
        envelope = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if isinstance(envelope, dict) and envelope.get("encoding") == "fernet":
        from app.services.encryption import decrypt_value

        try:
            envelope = json.loads(decrypt_value(envelope.get("ciphertext") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return {"attempt_id": row["attempt_id"], "attempt_no": int(row["attempt_no"]), "result": envelope}


def finish_harness_attempt(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    attempt_id: str,
    status: str,
    output: dict | None = None,
    error_code: str | None = None,
    lease_owner: str | None = None,
) -> dict:
    """Close an Attempt and its Action without overwriting prior attempts."""
    if status not in {"succeeded", "failed"}:
        raise ValueError("attempt status must be succeeded or failed")
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            attempt = conn.execute(
                "SELECT * FROM interview_attempts WHERE id = ? AND turn_id = ? "
                "AND conversation_id = ? AND user_id = ?",
                (attempt_id, turn_id, conversation_id, user_id),
            ).fetchone()
            if not attempt:
                raise ValueError("attempt does not belong to the caller")
            _assert_lease_conn(conn, turn_id, lease_owner)
            attempt_update = conn.execute(
                "UPDATE interview_attempts SET status = ?, finished_at = CURRENT_TIMESTAMP, "
                "error_code = ? WHERE id = ? AND status = 'active'",
                (status, error_code, attempt_id),
            )
            if attempt_update.rowcount:
                action_status = "completed" if status == "succeeded" else "failed"
                conn.execute(
                    "UPDATE interview_actions SET status = ?, output_json = ?, error_code = ?, "
                    "finished_at = CURRENT_TIMESTAMP WHERE id = ? AND current_attempt_no = ?",
                    (
                        action_status,
                        json.dumps(output or {}, ensure_ascii=False, sort_keys=True, default=str),
                        error_code,
                        attempt["action_id"],
                        int(attempt["attempt_no"]),
                    ),
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
    lease_owner: str | None = None,
) -> dict:
    """Append one immutable prompt/reasoning/tool/output artifact."""
    if visibility not in {"user", "audit", "model"}:
        raise ValueError("invalid artifact visibility")
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    stored_content = canonical
    if artifact_type in {"provider_request", "provider_response", "provider_error", "raw_provider_response"}:
        try:
            from app.services.encryption import encrypt_value

            stored_content = json.dumps(
                {"encoding": "fernet", "ciphertext": encrypt_value(canonical)},
                ensure_ascii=False,
                sort_keys=True,
            )
        except RuntimeError:
            # Local/offline test environments may intentionally omit the key;
            # production startup validation requires JWT_SECRET.
            logger.warning("Harness artifact encryption key is unavailable; storing audit artifact plaintext")
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
            _assert_lease_conn(conn, turn_id, lease_owner)
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
                    stored_content,
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

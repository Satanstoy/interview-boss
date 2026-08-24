"""Harness 2.0 append-only turn events and transactional outbox."""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import get_db_connection


class TurnEventConflict(ValueError):
    """The same event identity was reused with different event data."""


def _event_dict(row) -> dict[str, Any]:
    result = dict(row)
    try:
        payload = json.loads(result.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    result["payload"] = payload if isinstance(payload, dict) else {}
    result.pop("payload_json", None)
    if result.get("sequence") is not None:
        result["sequence"] = int(result["sequence"])
    result["session_id"] = result.get("conversation_id")
    result["turn_run_id"] = result.get("turn_id")
    result["type"] = result.get("event_type")
    version = result.get("schema_version") or 1
    result["schema_version"] = (
        version
        if isinstance(version, str) and version.startswith("turn-event-v")
        else f"turn-event-v{int(version)}"
    )
    result["occurred_at"] = result.get("created_at")
    return result


def append_turn_event(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    event_id: str,
    event_type: str,
    action_id: str | None,
    phase: str | None,
    channel: str,
    payload: dict[str, Any] | None,
    visibility: str = "user",
    schema_version: int = 1,
) -> dict[str, Any]:
    """Append one immutable event and its outbox record atomically."""
    normalized_event_id = str(event_id or "").strip()
    if not normalized_event_id:
        raise ValueError("event_id is required")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = _append_turn_event_conn(
                conn,
                user_id=user_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                event_id=normalized_event_id,
                event_type=event_type,
                action_id=action_id,
                phase=phase,
                channel=channel,
                payload=payload,
                visibility=visibility,
                schema_version=schema_version,
            )
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise


def _append_turn_event_conn(
    conn,
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    event_id: str,
    event_type: str,
    action_id: str | None,
    phase: str | None,
    channel: str,
    payload: dict[str, Any],
    visibility: str,
    schema_version: int,
) -> dict[str, Any]:
    """Append an event while the caller owns the surrounding transaction."""
    encoded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    existing = conn.execute(
        "SELECT event_id, conversation_id, turn_id, sequence, event_type, action_id, phase, "
        "channel, visibility, schema_version, payload_json, created_at FROM interview_events "
        "WHERE turn_id = ? AND event_id = ?",
        (turn_id, event_id),
    ).fetchone()
    if existing:
        same = (
            existing["event_type"] == event_type
            and existing["action_id"] == action_id
            and existing["phase"] == phase
            and existing["channel"] == channel
            and existing["visibility"] == visibility
            and int(existing["schema_version"] or 1) == int(schema_version)
            and existing["payload_json"] == encoded_payload
        )
        if not same:
            raise TurnEventConflict(event_id)
        return _event_dict(existing)

    turn = conn.execute(
        "SELECT user_id, conversation_id FROM chat_turns WHERE id = ?",
        (turn_id,),
    ).fetchone()
    if (
        not turn
        or int(turn["user_id"]) != int(user_id)
        or turn["conversation_id"] != conversation_id
    ):
        raise LookupError("turn not found or not owned")

    sequence = int(
        conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM interview_events WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO interview_events "
        "(user_id, conversation_id, turn_id, event_key, event_type, payload_json, "
        "schema_version, event_id, sequence, action_id, phase, channel, visibility) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            conversation_id,
            turn_id,
            event_id,
            event_type,
            encoded_payload,
            schema_version,
            event_id,
            sequence,
            action_id,
            phase,
            channel,
            visibility,
        ),
    )
    conn.execute(
        "INSERT INTO interview_event_outbox "
        "(event_id, user_id, conversation_id, turn_id, sequence, event_type, payload_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_id, user_id, conversation_id, turn_id, sequence, event_type, encoded_payload),
    )
    conn.execute(
        "UPDATE chat_turns SET latest_sequence = MAX(latest_sequence, ?), "
        "turn_run_version = turn_run_version + 1 WHERE id = ?",
        (sequence, turn_id),
    )
    row = conn.execute(
        "SELECT event_id, conversation_id, turn_id, sequence, event_type, action_id, phase, "
        "channel, visibility, schema_version, payload_json, created_at FROM interview_events "
        "WHERE turn_id = ? AND event_id = ?",
        (turn_id, event_id),
    ).fetchone()
    return _event_dict(row)


def get_turn_events(
    turn_id: str,
    *,
    user_id: int,
    conversation_id: str,
    after_sequence: int = 0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Read owned events in durable sequence order for SSE replay."""
    safe_limit = max(1, min(int(limit), 2000))
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT e.event_id, e.conversation_id, e.turn_id, e.sequence, e.event_type, "
            "e.action_id, e.phase, e.channel, e.visibility, e.schema_version, "
            "e.payload_json, e.created_at "
            "FROM interview_events e "
            "WHERE e.turn_id = ? AND e.user_id = ? AND e.conversation_id = ? "
            "AND e.sequence > ? ORDER BY e.sequence ASC LIMIT ?",
            (turn_id, user_id, conversation_id, max(0, int(after_sequence)), safe_limit),
        ).fetchall()
    return [_event_dict(row) for row in rows]


def get_turn_event_sequence(
    turn_id: str,
    *,
    event_id: str,
    user_id: int,
    conversation_id: str,
) -> int | None:
    """Resolve an SSE Last-Event-ID to the authoritative turn sequence."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT sequence FROM interview_events "
            "WHERE turn_id = ? AND event_id = ? AND user_id = ? "
            "AND conversation_id = ?",
            (turn_id, str(event_id), user_id, conversation_id),
        ).fetchone()
    return int(row["sequence"]) if row else None


def claim_turn_event_outbox(*, limit: int = 50, lease_seconds: int = 30) -> list[dict[str, Any]]:
    """Claim durable event notifications for an SSE/broker publisher."""
    safe_limit = max(1, min(int(limit), 500))
    safe_lease = max(1, min(int(lease_seconds), 3600))
    claimed: list[dict[str, Any]] = []
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                "SELECT * FROM interview_event_outbox "
                "WHERE status IN ('pending', 'failed') "
                "AND available_at <= CURRENT_TIMESTAMP "
                "AND (locked_at IS NULL OR locked_at <= datetime('now')) "
                "ORDER BY available_at ASC, created_at ASC LIMIT ?",
                (safe_limit,),
            ).fetchall()
            for row in rows:
                updated = conn.execute(
                    "UPDATE interview_event_outbox SET locked_at = datetime('now', ?), "
                    "attempts = attempts + 1 WHERE event_id = ? "
                    "AND status IN ('pending', 'failed') "
                    "AND available_at <= CURRENT_TIMESTAMP "
                    "AND (locked_at IS NULL OR locked_at <= datetime('now'))",
                    (f"+{safe_lease} seconds", row["event_id"]),
                )
                if updated.rowcount:
                    item = dict(row)
                    item["attempts"] = int(row["attempts"] or 0) + 1
                    claimed.append(item)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return claimed


def mark_turn_event_outbox_published(
    event_id: str,
    *,
    success: bool = True,
    error: str | None = None,
    retry_delay_seconds: int = 5,
) -> bool:
    """Acknowledge or release a claimed notification without changing the event."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if success:
                updated = conn.execute(
                    "UPDATE interview_event_outbox SET status = 'published', "
                    "locked_at = NULL, published_at = CURRENT_TIMESTAMP, last_error = NULL "
                    "WHERE event_id = ? AND status != 'published'",
                    (str(event_id),),
                )
            else:
                delay = max(1, min(int(retry_delay_seconds), 86400))
                updated = conn.execute(
                    "UPDATE interview_event_outbox SET status = 'failed', locked_at = NULL, "
                    "available_at = datetime('now', ?), last_error = ? WHERE event_id = ?",
                    (f"+{delay} seconds", str(error or "publish_failed")[:500], str(event_id)),
                )
            conn.commit()
            return bool(updated.rowcount)
        except Exception:
            conn.rollback()
            raise

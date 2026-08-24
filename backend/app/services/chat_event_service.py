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
        version if isinstance(version, str) and version.startswith("turn-event-v")
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

    encoded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT event_id, conversation_id, turn_id, sequence, event_type, action_id, phase, "
            "channel, visibility, schema_version, payload_json, created_at FROM interview_events "
            "WHERE turn_id = ? AND event_id = ?",
            (turn_id, normalized_event_id),
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
                conn.rollback()
                raise TurnEventConflict(normalized_event_id)
            result = _event_dict(existing)
            conn.rollback()
            return result

        turn = conn.execute(
            "SELECT user_id, conversation_id FROM chat_turns WHERE id = ?",
            (turn_id,),
        ).fetchone()
        if not turn or int(turn["user_id"]) != int(user_id) or turn["conversation_id"] != conversation_id:
            conn.rollback()
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
                normalized_event_id,
                event_type,
                encoded_payload,
                schema_version,
                normalized_event_id,
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
            (
                normalized_event_id,
                user_id,
                conversation_id,
                turn_id,
                sequence,
                event_type,
                encoded_payload,
            ),
        )
        row = conn.execute(
            "SELECT event_id, conversation_id, turn_id, sequence, event_type, action_id, phase, "
            "channel, visibility, schema_version, payload_json, created_at FROM interview_events "
            "WHERE turn_id = ? AND event_id = ?",
            (turn_id, normalized_event_id),
        ).fetchone()
        conn.commit()
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

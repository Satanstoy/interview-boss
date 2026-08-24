"""回合(turn)生命周期服务 - 从 chat_service 机械抽取。

职责:对话回合的原子预留/推进/取消/终结、会话 fence 管理、幂等唯一性、
side-effect job 入队、开场白生成。

共享原始块(异常/ChatTurn/JSON)来自 chat_common,避免循环依赖。
"""
import json
import hashlib
import logging
import uuid
from typing import Optional
from app.db.connection import get_db_connection
from app.services.chat_common import (
    ChatTurn,
    ConversationNotFound,
    ConversationNotWritable,
    TurnCancelled,
    TurnIdempotencyConflict,
    TurnInProgress,
    TurnNotFound,
    TurnUserMessageConflict,
    _chat_turn_from_row,
    _safe_json_loads,
    build_turn_request_fingerprint,
)
from app.services.harness_state_service import (
    commit_interview_ledger_conn,
    ensure_interview_ledger_conn,
)
from app.services.chat_event_service import _append_turn_event_conn, TurnEventLeaseLost

logger = logging.getLogger("interview-boss")


def get_chat_turn(
    turn_id: str,
    conversation_id: str | None = None,
    user_id: int | None = None,
) -> Optional[dict]:
    """Return a JSON-safe turn snapshot for status/reconciliation paths."""
    with get_db_connection() as conn:
        where = ["t.id = ?"]
        params: list[object] = [turn_id]
        if conversation_id is not None:
            where.append("t.conversation_id = ?")
            params.append(conversation_id)
        if user_id is not None:
            where.append("t.user_id = ?")
            params.append(user_id)
        row = conn.execute(
            "SELECT t.id, t.conversation_id, t.user_id, t.client_request_id, t.fence, t.status, "
            "t.user_message_id, t.assistant_message_id, t.cancel_reason, t.error_code, "
            "t.request_fingerprint, t.revision_of_message_id, t.revision_of_turn_id, "
            "t.harness_status, t.context_pack_hash, t.stable_prefix_hash, t.latest_sequence, "
            "t.created_at, t.finished_at, "
            "a.content AS assistant_content, a.metadata AS assistant_metadata "
            "FROM chat_turns t LEFT JOIN chat_messages a "
            "ON a.id = t.assistant_message_id WHERE " + " AND ".join(where),
            params,
        ).fetchone()
    if not row:
        return None
    snapshot = dict(row)
    snapshot["assistant_metadata"] = _safe_json_loads(
        snapshot.get("assistant_metadata")
    )
    return snapshot


def reserve_chat_turn(
    conversation_id: str,
    user_id: int,
    client_request_id: str,
    content: str,
    request_fingerprint: str | None = None,
    existing_user_message_id: int | None = None,
    revision_of_turn_id: str | None = None,
    harness_version: str | None = None,
    model: str | None = None,
) -> ChatTurn:
    """Atomically claim one active turn and persist its user message.

    Reusing the same client request id returns the original turn without adding
    another user message. A pre-created first message can be claimed by ID so
    the delayed conversation creation flow does not insert it twice. A different
    request cannot race an existing running turn because the partial unique
    index is backed by an immediate transaction.
    """
    request_id = str(client_request_id or "").strip()
    if not request_id:
        raise ValueError("client_request_id is required")
    fingerprint = request_fingerprint or build_turn_request_fingerprint(
        content, revision_of_turn_id=revision_of_turn_id
    )

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conversation = conn.execute(
                "SELECT user_id, status, session_version, mode, jd_id, resume_text, "
                "language, question_strategy, interview_config_json, provider_policy_json "
                "FROM chat_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not conversation or int(conversation["user_id"]) != int(user_id):
                raise ConversationNotFound("conversation not found")
            if conversation["status"] != "active":
                raise ConversationNotWritable("conversation is not writable")
            ensure_interview_ledger_conn(
                conn, user_id=user_id, conversation_id=conversation_id
            )
            ledger = conn.execute(
                "SELECT ledger_version FROM interview_ledgers WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            session_version = int(conversation["session_version"] or 1)
            ledger_version = int(ledger["ledger_version"] if ledger else 1)
            turn_base_snapshot = json.dumps(
                {
                    "mode": conversation["mode"],
                    "jd_id": conversation["jd_id"],
                    "resume_text": conversation["resume_text"],
                    "language": conversation["language"],
                    "question_strategy": conversation["question_strategy"],
                    "interview_config": _safe_json_loads(
                        conversation["interview_config_json"]
                    ),
                    "provider_policy": _safe_json_loads(
                        conversation["provider_policy_json"]
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )

            if revision_of_turn_id:
                source = conn.execute(
                    "SELECT id FROM chat_turns "
                    "WHERE id = ? AND conversation_id = ? AND user_id = ?",
                    (revision_of_turn_id, conversation_id, user_id),
                ).fetchone()
                if not source:
                    raise TurnNotFound("revision source turn not found")

            existing = conn.execute(
                "SELECT id, conversation_id, user_id, client_request_id, fence, status, "
                "user_message_id, assistant_message_id, request_fingerprint, "
                "revision_of_message_id, revision_of_turn_id FROM chat_turns "
                "WHERE conversation_id = ? AND client_request_id = ?",
                (conversation_id, request_id),
            ).fetchone()
            if existing:
                stored_fingerprint = existing["request_fingerprint"] or ""
                if not stored_fingerprint:
                    original = conn.execute(
                        "SELECT content FROM chat_messages WHERE id = ?",
                        (existing["user_message_id"],),
                    ).fetchone()
                    legacy_fingerprint = build_turn_request_fingerprint(
                        original["content"] if original else ""
                    )
                    if not original or legacy_fingerprint != fingerprint:
                        raise TurnIdempotencyConflict(
                            existing["id"], existing["status"]
                        )
                    conn.execute(
                        "UPDATE chat_turns SET request_fingerprint = ? WHERE id = ?",
                        (fingerprint, existing["id"]),
                    )
                    conn.commit()
                    return ChatTurn(
                        id=existing["id"],
                        conversation_id=existing["conversation_id"],
                        user_id=int(existing["user_id"]),
                        client_request_id=existing["client_request_id"],
                        fence=int(existing["fence"]),
                        status=existing["status"],
                        user_message_id=existing["user_message_id"],
                        assistant_message_id=existing["assistant_message_id"],
                        request_fingerprint=fingerprint,
                        revision_of_message_id=existing["revision_of_message_id"],
                        revision_of_turn_id=(
                            existing["revision_of_turn_id"]
                            if "revision_of_turn_id" in existing.keys()
                            else None
                        ),
                        created=False,
                    )
                if stored_fingerprint and stored_fingerprint != fingerprint:
                    raise TurnIdempotencyConflict(existing["id"], existing["status"])
                conn.rollback()
                return _chat_turn_from_row(existing, created=False)

            running = conn.execute(
                "SELECT id FROM chat_turns "
                "WHERE conversation_id = ? AND status = 'running' LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if running:
                raise TurnInProgress("conversation already has a running turn")

            user_message_id = None
            precreated_metadata = None
            if existing_user_message_id is not None:
                precreated = conn.execute(
                    "SELECT id, content, metadata FROM chat_messages "
                    "WHERE id = ? AND conversation_id = ? AND role = 'user'",
                    (existing_user_message_id, conversation_id),
                ).fetchone()
                if not precreated or precreated["content"] != content:
                    raise TurnUserMessageConflict(
                        "pre-created user message does not match this turn"
                    )
                precreated_metadata = _safe_json_loads(precreated["metadata"])
                if not precreated_metadata.pop("precreated", False):
                    raise TurnUserMessageConflict(
                        "user message is already claimed by another turn"
                    )
                linked = conn.execute(
                    "SELECT id FROM chat_turns WHERE user_message_id = ? LIMIT 1",
                    (existing_user_message_id,),
                ).fetchone()
                if linked:
                    raise TurnUserMessageConflict(
                        "user message is already claimed by another turn"
                    )
                user_message_id = int(existing_user_message_id)

            fence_row = conn.execute(
                "SELECT COALESCE(MAX(fence), 0) + 1 AS next_fence "
                "FROM chat_turns WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            fence = int(fence_row["next_fence"])
            turn_id = str(uuid.uuid4())
            if user_message_id is None:
                conn.execute(
                    "INSERT INTO chat_turns "
                    "(id, conversation_id, user_id, client_request_id, fence, status, "
                    "request_fingerprint, revision_of_turn_id, harness_status, session_version, "
                    "ledger_version_at_start, turn_base_snapshot_json, started_at) "
                    "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, 'running', ?, ?, ?, CURRENT_TIMESTAMP)",
                    (
                        turn_id,
                        conversation_id,
                        user_id,
                        request_id,
                        fence,
                        fingerprint,
                        revision_of_turn_id,
                        session_version,
                        ledger_version,
                        turn_base_snapshot,
                    ),
                )
                message_cursor = conn.execute(
                    "INSERT INTO chat_messages "
                    "(conversation_id, role, content, token_count, metadata) "
                    "VALUES (?, 'user', ?, 0, ?)",
                    (
                        conversation_id,
                        content,
                        json.dumps(
                            {
                                "turn_id": turn_id,
                                "turn_fence": fence,
                                **({"model": model} if model else {}),
                                **(
                                    {"revision_of_turn_id": revision_of_turn_id}
                                    if revision_of_turn_id
                                    else {}
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                user_message_id = message_cursor.lastrowid
                conn.execute(
                    "UPDATE chat_turns SET user_message_id = ? WHERE id = ?",
                    (user_message_id, turn_id),
                )
            else:
                conn.execute(
                    "INSERT INTO chat_turns "
                    "(id, conversation_id, user_id, client_request_id, fence, status, "
                    "user_message_id, request_fingerprint, revision_of_turn_id, "
                    "harness_status, session_version, "
                    "ledger_version_at_start, turn_base_snapshot_json, started_at) "
                    "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, 'running', ?, ?, ?, CURRENT_TIMESTAMP)",
                    (
                        turn_id,
                        conversation_id,
                        user_id,
                        request_id,
                        fence,
                        user_message_id,
                        fingerprint,
                        revision_of_turn_id,
                        session_version,
                        ledger_version,
                        turn_base_snapshot,
                    ),
                )
                precreated_metadata.update(
                    {
                        "turn_id": turn_id,
                        "turn_fence": fence,
                        **({"model": model} if model else {}),
                        **(
                            {"revision_of_turn_id": revision_of_turn_id}
                            if revision_of_turn_id
                            else {}
                        ),
                    }
                )
            if precreated_metadata is not None:
                conn.execute(
                    "UPDATE chat_messages SET metadata = ? WHERE id = ?",
                    (json.dumps(precreated_metadata, ensure_ascii=False), user_message_id),
                )
            if harness_version == "2.0":
                _append_turn_event_conn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_id=f"evt:{turn_id}:started",
                    event_type="turn.started",
                    action_id=None,
                    phase="observe_propose",
                    channel="system",
                    payload={
                        "client_request_id": request_id,
                        "session_id": conversation_id,
                        "harness_version": "2.0",
                    },
                    visibility="user",
                    schema_version=1,
                )
                _append_turn_event_conn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_id=f"evt:{turn_id}:queued",
                    event_type="turn.queued",
                    action_id=None,
                    phase="observe_propose",
                    channel="system",
                    payload={
                        "queue": "interview-turn",
                        "dispatch_state": "pending_dispatch",
                    },
                    visibility="user",
                    schema_version=1,
                )
            conn.execute(
                "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ? AND status = 'active'",
                (conversation_id, user_id),
            )
            conn.commit()
            return ChatTurn(
                id=turn_id,
                conversation_id=conversation_id,
                user_id=int(user_id),
                client_request_id=request_id,
                fence=fence,
                status="running",
                user_message_id=user_message_id,
                request_fingerprint=fingerprint,
                revision_of_turn_id=revision_of_turn_id,
            )
        except Exception:
            conn.rollback()
            raise


def reserve_chat_edit_revision(
    conversation_id: str,
    user_id: int,
    source_turn_id: str,
    content: str,
    client_request_id: str,
    model: str | None = None,
    harness_version: str | None = None,
) -> ChatTurn:
    """Create a new user TurnRun while preserving the source TurnRun."""
    request_fingerprint = build_turn_request_fingerprint(
        content,
        model=model,
        revision_of_turn_id=source_turn_id,
    )
    return reserve_chat_turn(
        conversation_id,
        user_id,
        client_request_id,
        content,
        request_fingerprint=request_fingerprint,
        revision_of_turn_id=source_turn_id,
        harness_version=harness_version,
        model=model,
    )


def _load_owned_turn(conn, turn_id: str, conversation_id: str, user_id: int):
    row = conn.execute(
        "SELECT id, conversation_id, user_id, client_request_id, fence, status, "
        "user_message_id, assistant_message_id, lease_owner FROM chat_turns "
        "WHERE id = ? AND conversation_id = ? AND user_id = ?",
        (turn_id, conversation_id, user_id),
    ).fetchone()
    if not row:
        raise TurnNotFound("turn not found")
    return row


def reserve_chat_revision(
    conversation_id: str,
    user_id: int,
    assistant_message_id: int,
    client_request_id: str,
    model: str | None = None,
    harness_version: str | None = None,
) -> tuple[ChatTurn, str]:
    """Reserve a new assistant generation without inserting another user message."""
    request_id = str(client_request_id or "").strip()
    if not request_id:
        raise ValueError("client_request_id is required")

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conversation = conn.execute(
                "SELECT user_id, status, session_version, mode, jd_id, resume_text, "
                "language, question_strategy, interview_config_json, provider_policy_json "
                "FROM chat_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not conversation or int(conversation["user_id"]) != int(user_id):
                raise ConversationNotFound("conversation not found")
            if conversation["status"] != "active":
                raise ConversationNotWritable("conversation is not writable")
            ensure_interview_ledger_conn(
                conn, user_id=user_id, conversation_id=conversation_id
            )
            ledger = conn.execute(
                "SELECT ledger_version FROM interview_ledgers WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            session_version = int(conversation["session_version"] or 1)
            ledger_version = int(ledger["ledger_version"] if ledger else 1)
            turn_base_snapshot = json.dumps(
                {
                    "mode": conversation["mode"],
                    "jd_id": conversation["jd_id"],
                    "resume_text": conversation["resume_text"],
                    "language": conversation["language"],
                    "question_strategy": conversation["question_strategy"],
                    "interview_config": _safe_json_loads(
                        conversation["interview_config_json"]
                    ),
                    "provider_policy": _safe_json_loads(
                        conversation["provider_policy_json"]
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )

            target = conn.execute(
                "SELECT t.id AS source_turn_id, t.user_message_id, t.assistant_message_id, "
                "u.content AS user_content "
                "FROM chat_turns t "
                "JOIN chat_messages a ON a.id = t.assistant_message_id "
                "JOIN chat_messages u ON u.id = t.user_message_id "
                "WHERE t.assistant_message_id = ? AND t.conversation_id = ? "
                "AND t.user_id = ? AND a.role = 'assistant' AND u.role = 'user'",
                (assistant_message_id, conversation_id, user_id),
            ).fetchone()
            if not target:
                raise TurnNotFound("assistant message is not revisionable")

            fingerprint = build_turn_request_fingerprint(
                target["user_content"],
                model=model,
                revision_of_message_id=int(assistant_message_id),
            )
            existing = conn.execute(
                "SELECT id, conversation_id, user_id, client_request_id, fence, status, "
                "user_message_id, assistant_message_id, request_fingerprint, "
                "revision_of_message_id FROM chat_turns "
                "WHERE conversation_id = ? AND client_request_id = ?",
                (conversation_id, request_id),
            ).fetchone()
            if existing:
                stored_fingerprint = existing["request_fingerprint"] or ""
                if stored_fingerprint and stored_fingerprint != fingerprint:
                    raise TurnIdempotencyConflict(existing["id"], existing["status"])
                conn.rollback()
                return _chat_turn_from_row(existing, created=False), target[
                    "user_content"
                ]

            running = conn.execute(
                "SELECT id FROM chat_turns "
                "WHERE conversation_id = ? AND status = 'running' LIMIT 1",
                (conversation_id,),
            ).fetchone()
            if running:
                raise TurnInProgress("conversation already has a running turn")

            fence_row = conn.execute(
                "SELECT COALESCE(MAX(fence), 0) + 1 AS next_fence "
                "FROM chat_turns WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            fence = int(fence_row["next_fence"])
            turn_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO chat_turns "
                "(id, conversation_id, user_id, client_request_id, fence, status, "
                "user_message_id, request_fingerprint, revision_of_message_id, "
                "revision_of_turn_id, harness_status, session_version, "
                "ledger_version_at_start, turn_base_snapshot_json, started_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, 'running', ?, ?, ?, CURRENT_TIMESTAMP)",
                (
                    turn_id,
                    conversation_id,
                    user_id,
                    request_id,
                    fence,
                    target["user_message_id"],
                    fingerprint,
                    assistant_message_id,
                    target["source_turn_id"],
                    session_version,
                    ledger_version,
                    turn_base_snapshot,
                ),
            )
            if harness_version == "2.0":
                _append_turn_event_conn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_id=f"evt:{turn_id}:started",
                    event_type="turn.started",
                    action_id=None,
                    phase="observe_propose",
                    channel="system",
                    payload={
                        "client_request_id": request_id,
                        "session_id": conversation_id,
                        "harness_version": "2.0",
                    },
                    visibility="user",
                    schema_version=1,
                )
            conn.commit()
            return (
                ChatTurn(
                    id=turn_id,
                    conversation_id=conversation_id,
                    user_id=int(user_id),
                    client_request_id=request_id,
                    fence=fence,
                    status="running",
                    user_message_id=target["user_message_id"],
                    request_fingerprint=fingerprint,
                    revision_of_message_id=assistant_message_id,
                    revision_of_turn_id=target["source_turn_id"],
                ),
                target["user_content"],
            )
        except Exception:
            conn.rollback()
            raise


def cancel_chat_turn(
    turn_id: str,
    conversation_id: str,
    user_id: int,
    reason: str = "client_stop",
    defer_terminal: bool = False,
    lease_owner: str | None = None,
    harness_events: bool = False,
) -> ChatTurn:
    """Request or finalize cancellation; repeated cancellation is idempotent.

    Harness 2.0 uses cooperative cancellation: the request event is durable,
    while the worker wins the terminal transition after it observes the
    request. Legacy inline SSE keeps its historical immediate transition.
    """
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _load_owned_turn(conn, turn_id, conversation_id, user_id)
            if lease_owner is not None and row["lease_owner"] != str(lease_owner):
                raise TurnEventLeaseLost(turn_id)
            if row["status"] == "running":
                if defer_terminal:
                    updated = conn.execute(
                        "UPDATE chat_turns SET cancel_reason = ?, "
                        "heartbeat_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND status = 'running' AND cancel_reason IS NULL",
                        (reason[:120], turn_id),
                    )
                    if updated.rowcount:
                        _append_turn_event_conn(
                            conn,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            event_id=f"evt:{turn_id}:cancel-requested",
                            event_type="turn.cancel_requested",
                            action_id=None,
                            phase="commit",
                            channel="system",
                            payload={"reason": reason[:120]},
                            visibility="user",
                            schema_version=1,
                        )
                else:
                    conn.execute(
                        "UPDATE chat_turns SET status = 'cancelled', harness_status = 'cancelled', "
                        "terminal_reason = ?, cancel_reason = ?, finished_at = CURRENT_TIMESTAMP, "
                        + ("heartbeat_at = CURRENT_TIMESTAMP " if lease_owner is not None else
                           "lease_owner = NULL, lease_expires_at = NULL, heartbeat_at = CURRENT_TIMESTAMP ")
                        + "WHERE id = ? AND status = 'running' "
                        + ("AND lease_owner = ?" if lease_owner is not None else ""),
                        (
                            reason[:120],
                            reason[:120],
                            turn_id,
                            *((str(lease_owner),) if lease_owner is not None else ()),
                        ),
                    )
                    if lease_owner is not None and harness_events:
                        _append_turn_event_conn(
                            conn,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            event_id=f"evt:{turn_id}:cancelled",
                            event_type="turn.cancelled",
                            action_id=None,
                            phase="commit",
                            channel="system",
                            payload={"reason": reason[:120]},
                            visibility="user",
                            schema_version=1,
                            lease_owner=lease_owner,
                        )
                        conn.execute(
                            "UPDATE chat_turns SET lease_owner = NULL, lease_expires_at = NULL "
                            "WHERE id = ? AND lease_owner = ?",
                            (turn_id, str(lease_owner)),
                        )
            conn.commit()
            return _chat_turn_from_row(
                conn.execute(
                    "SELECT id, conversation_id, user_id, client_request_id, fence, status, "
                    "user_message_id, assistant_message_id, request_fingerprint, "
                    "revision_of_message_id FROM chat_turns WHERE id = ?",
                    (turn_id,),
                ).fetchone()
            )
        except Exception:
            conn.rollback()
            raise


def assert_chat_turn_active(
    turn_id: str,
    fence: int,
    conversation_id: str,
    user_id: int,
    lease_owner: str | None = None,
) -> None:
    """Reject stale workers before they perform turn-owned side effects."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT t.status, t.cancel_reason, t.lease_owner, c.status AS conversation_status "
            "FROM chat_turns t JOIN chat_conversations c ON c.id = t.conversation_id "
            "WHERE t.id = ? AND t.fence = ? AND t.conversation_id = ? AND t.user_id = ?",
            (turn_id, fence, conversation_id, user_id),
        ).fetchone()
    if not row:
        raise TurnNotFound("turn not found")
    if row["status"] != "running" or row["conversation_status"] != "active":
        raise TurnCancelled("turn is no longer active")
    if row["cancel_reason"]:
        raise TurnCancelled("turn cancellation requested")
    if lease_owner is not None and row["lease_owner"] != str(lease_owner):
        raise TurnEventLeaseLost(turn_id)


def _enqueue_side_effect_job_conn(
    conn,
    *,
    kind: str,
    user_id: int,
    conversation_id: str,
    source_turn_id: str,
    payload: dict,
) -> str:
    """Insert one idempotent durable side-effect handoff in an open transaction."""
    job_id = str(uuid.uuid4())
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO chat_side_effect_jobs
            (id, kind, user_id, conversation_id, source_turn_id, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            kind,
            user_id,
            conversation_id,
            source_turn_id,
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
    if cursor.rowcount:
        return job_id
    row = conn.execute(
        "SELECT id FROM chat_side_effect_jobs WHERE kind = ? AND source_turn_id = ?",
        (kind, source_turn_id),
    ).fetchone()
    if not row:
        raise RuntimeError("side-effect job insert did not produce a job")
    return row["id"]


def finalize_chat_turn(
    turn_id: str,
    fence: int,
    conversation_id: str,
    user_id: int,
    content: str,
    metadata: Optional[dict] = None,
    harness_events: bool = False,
    lease_owner: str | None = None,
) -> Optional[int]:
    """Persist assistant output only for the still-running turn fence.

    Harness 2.0 callers set ``harness_events`` so the assistant completion,
    commit completion, and terminal event are written in this same database
    transaction as the Ledger and formal assistant message.  The legacy
    inline SSE path leaves it false and keeps its historical event behavior.
    """
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT t.status, t.cancel_reason, t.lease_owner, t.revision_of_message_id, t.revision_of_turn_id, "
                "t.request_fingerprint, "
                "c.status AS conversation_status "
                "FROM chat_turns t JOIN chat_conversations c ON c.id = t.conversation_id "
                "WHERE t.id = ? AND t.fence = ? AND t.conversation_id = ? AND t.user_id = ?",
                (turn_id, fence, conversation_id, user_id),
            ).fetchone()
            if not row:
                raise TurnNotFound("turn not found")
            if (
                row["status"] != "running"
                or row["conversation_status"] != "active"
                or row["cancel_reason"]
                or (lease_owner is not None and row["lease_owner"] != str(lease_owner))
            ):
                if lease_owner is not None and row["lease_owner"] != str(lease_owner):
                    raise TurnEventLeaseLost(turn_id)
                raise TurnCancelled("turn is no longer active")

            commit_interview_ledger_conn(
                conn,
                turn_id=turn_id,
                fence=fence,
                conversation_id=conversation_id,
                user_id=user_id,
                metadata=metadata or {},
            )

            persisted_metadata = dict(metadata or {})
            persisted_metadata.setdefault("turn_id", turn_id)
            persisted_metadata.setdefault("turn_fence", fence)
            if harness_events and persisted_metadata.get("question_source") != "agent_internal":
                selected_question = persisted_metadata.get("selected_question") or {}
                question_id = selected_question.get("id") if isinstance(selected_question, dict) else None
                try:
                    if question_id is not None:
                        conn.execute(
                            "INSERT INTO interview_asked_questions "
                            "(user_id, conversation_id, question_id) VALUES (?, ?, ?)",
                            (user_id, conversation_id, int(question_id)),
                        )
                except (TypeError, ValueError):
                    logger.warning("Ignoring invalid selected question id for turn %s", turn_id)
            if row["request_fingerprint"]:
                persisted_metadata.setdefault(
                    "request_fingerprint", row["request_fingerprint"]
                )
            if row["revision_of_message_id"] is not None:
                persisted_metadata.setdefault(
                    "revision_of_message_id", row["revision_of_message_id"]
                )
                revision_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM chat_turns "
                    "WHERE revision_of_message_id = ? AND status = 'completed' "
                    "AND assistant_message_id IS NOT NULL",
                    (row["revision_of_message_id"],),
                ).fetchone()["count"]
                persisted_metadata.setdefault(
                    "revision_number", int(revision_count) + 1
                )
            if row["revision_of_turn_id"] is not None:
                persisted_metadata.setdefault(
                    "revision_of_turn_id", row["revision_of_turn_id"]
                )

            assistant_id = None
            generation_id = None
            if content:
                generation_id = str(uuid.uuid4())
                persisted_metadata.setdefault("generation_id", generation_id)
                cursor = conn.execute(
                    "INSERT INTO chat_messages "
                    "(conversation_id, role, content, token_count, metadata) "
                    "VALUES (?, 'assistant', ?, 0, ?)",
                    (
                        conversation_id,
                        content,
                        json.dumps(persisted_metadata, ensure_ascii=False),
                    ),
                )
                assistant_id = cursor.lastrowid
                parent_generation = conn.execute(
                    "SELECT id FROM assistant_generations WHERE conversation_id = ? AND visible = 1 "
                    "ORDER BY created_at DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                conn.execute(
                    "UPDATE assistant_generations SET visible = 0 WHERE conversation_id = ?",
                    (conversation_id,),
                )
                contract = persisted_metadata.get("turn_contract")
                contract_hash = hashlib.sha256(
                    json.dumps(
                        contract or {}, ensure_ascii=False, sort_keys=True
                    ).encode("utf-8")
                ).hexdigest()
                evidence_refs = persisted_metadata.get("evidence_refs") or []
                conn.execute(
                    "INSERT INTO assistant_generations "
                    "(id, user_id, conversation_id, turn_id, message_id, parent_generation_id, "
                    "source_turn_id, contract_hash, evidence_refs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        generation_id,
                        user_id,
                        conversation_id,
                        turn_id,
                        assistant_id,
                        parent_generation["id"] if parent_generation else None,
                        turn_id,
                        contract_hash,
                        json.dumps(evidence_refs, ensure_ascii=False),
                    ),
                )
                coverage_events = persisted_metadata.get("coverage_events") or []
                for index, event in enumerate(coverage_events):
                    if not isinstance(event, dict):
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO interview_events "
                        "(user_id, conversation_id, turn_id, event_key, event_type, payload_json) "
                        "VALUES (?, ?, ?, ?, 'coverage', ?)",
                        (
                            user_id,
                            conversation_id,
                            turn_id,
                            f"coverage:{index}",
                            json.dumps(event, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                closing_stage = str(persisted_metadata.get("closing_stage") or "")
                target_state = {
                    "candidate_question_asked": "candidate_question",
                    "candidate_question_answered": "final_summary",
                    "final_summary": "final_summary",
                    "closed": "closed",
                }.get(closing_stage)
                if target_state:
                    conn.execute(
                        "INSERT OR IGNORE INTO interview_events "
                        "(user_id, conversation_id, turn_id, event_key, event_type, payload_json) "
                        "VALUES (?, ?, ?, ?, 'state_transition', ?)",
                        (
                            user_id,
                            conversation_id,
                            turn_id,
                            "state_transition:0",
                            json.dumps({"to": target_state}, ensure_ascii=False),
                        ),
                    )
            if harness_events:
                _append_turn_event_conn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_id=f"evt:{turn_id}:assistant-completed",
                    event_type="assistant.completed",
                    action_id=None,
                    phase="write_response",
                    channel="assistant",
                    payload={"content": content or "", "provisional": False},
                    visibility="user",
                    schema_version=1,
                    lease_owner=lease_owner,
                )
                _append_turn_event_conn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_id=f"evt:{turn_id}:commit-completed",
                    event_type="commit.completed",
                    action_id=None,
                    phase="commit",
                    channel="system",
                    payload={"status": "committed"},
                    visibility="user",
                    schema_version=1,
                    lease_owner=lease_owner,
                )
            updated = conn.execute(
                "UPDATE chat_turns SET status = 'completed', harness_status = 'completed', "
                "terminal_reason = 'completed', assistant_message_id = ?, "
                "finished_at = CURRENT_TIMESTAMP, "
                + ("lease_owner = NULL, lease_expires_at = NULL, " if lease_owner is None else "")
                + "heartbeat_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ? "
                "AND status = 'running' "
                + ("AND lease_owner = ?" if lease_owner is not None else ""),
                (
                    assistant_id,
                    turn_id,
                    fence,
                    conversation_id,
                    user_id,
                    *((str(lease_owner),) if lease_owner is not None else ()),
                ),
            )
            if updated.rowcount != 1:
                raise TurnCancelled("turn is no longer active")
            if harness_events:
                _append_turn_event_conn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_id=f"evt:{turn_id}:completed",
                    event_type="turn.completed",
                    action_id=None,
                    phase="commit",
                    channel="system",
                    payload={
                        "status": "completed",
                        "content": content or "",
                        "metadata": metadata or {},
                    },
                    visibility="user",
                    schema_version=1,
                    lease_owner=lease_owner,
                )

            if lease_owner is not None:
                conn.execute(
                    "UPDATE chat_turns SET lease_owner = NULL, lease_expires_at = NULL "
                    "WHERE id = ? AND fence = ? AND lease_owner = ?",
                    (turn_id, fence, str(lease_owner)),
                )

            user_row = conn.execute(
                "SELECT content FROM chat_messages WHERE id = ?",
                (
                    row["revision_of_message_id"]
                    if row["revision_of_message_id"]
                    else None,
                ),
            ).fetchone()
            source_user_row = conn.execute(
                "SELECT content FROM chat_messages WHERE id = "
                "(SELECT user_message_id FROM chat_turns WHERE id = ?)",
                (turn_id,),
            ).fetchone()
            if content and source_user_row:
                _enqueue_side_effect_job_conn(
                    conn,
                    kind="memory_extraction",
                    user_id=user_id,
                    conversation_id=conversation_id,
                    source_turn_id=turn_id,
                    payload={
                        "schema_version": 1,
                        "user_message": str(source_user_row["content"] or "")[:4000],
                        "assistant_response": str(content or "")[:4000],
                        "prior_question": str(user_row["content"] or "")[:400]
                        if user_row
                        else "",
                        "metadata": persisted_metadata,
                    },
                )
            conn.execute(
                "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ? AND status = 'active'",
                (conversation_id, user_id),
            )
            conn.commit()
            return assistant_id
        except Exception:
            conn.rollback()
            raise


def fail_chat_turn(
    turn_id: str,
    fence: int,
    conversation_id: str,
    user_id: int,
    error_code: str,
    lease_owner: str | None = None,
    harness_events: bool = False,
) -> None:
    """Mark a still-running turn failed without resurrecting old turns."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT status, lease_owner FROM chat_turns "
                "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ?",
                (turn_id, fence, conversation_id, user_id),
            ).fetchone()
            if not row:
                raise TurnNotFound("turn not found")
            if lease_owner is not None and row["lease_owner"] != str(lease_owner):
                raise TurnEventLeaseLost(turn_id)
            if row["status"] != "running":
                conn.commit()
                return
            safe_code = str(error_code or "turn_failed")[:120]
            updated = conn.execute(
                "UPDATE chat_turns SET status = 'failed', harness_status = 'failed', "
                "terminal_reason = ?, error_code = ?, finished_at = CURRENT_TIMESTAMP, "
                + ("heartbeat_at = CURRENT_TIMESTAMP " if harness_events else "lease_owner = NULL, "
                   "lease_expires_at = NULL, heartbeat_at = CURRENT_TIMESTAMP ")
                + "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ? "
                "AND status = 'running' "
                + ("AND lease_owner = ?" if lease_owner is not None else ""),
                (
                    safe_code,
                    safe_code,
                    turn_id,
                    fence,
                    conversation_id,
                    user_id,
                            *((str(lease_owner),) if lease_owner is not None else ()),
                ),
            )
            if updated.rowcount != 1:
                raise TurnCancelled("turn is no longer active")
            if harness_events:
                _append_turn_event_conn(
                    conn,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    event_id=f"evt:{turn_id}:failed",
                    event_type="turn.failed",
                    action_id=None,
                    phase="commit",
                    channel="system",
                    payload={"code": safe_code, "message": safe_code},
                    visibility="user",
                    schema_version=1,
                    lease_owner=lease_owner,
                )
                conn.execute(
                    "UPDATE chat_turns SET lease_owner = NULL, lease_expires_at = NULL "
                    "WHERE id = ? AND fence = ? AND lease_owner = ?",
                    (turn_id, fence, str(lease_owner)),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ═══════════════════════════════════════════════════
#  面试开场白
# ═══════════════════════════════════════════════════


def generate_opening_message(mode: str) -> str:
    """生成面试官开场白（静态文本，零 LLM 成本）"""
    if mode == "jd_resume":
        return (
            "你好，我是今天的面试官。我已经看过你的简历和目标岗位的 JD，"
            "接下来我们会围绕这个岗位的要求展开面试。\n\n"
            "请先简单做一下自我介绍吧。"
        )
    return (
        "你好，我是今天的面试官。接下来我们进行模拟面试练习，"
        "我会从题库中抽取题目来提问。\n\n"
        "请先简单做一下自我介绍吧。"
    )


# ═══════════════════════════════════════════════════
#  会话管理
# ═══════════════════════════════════════════════════

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
    SideEffectConflict,
    _chat_turn_from_row,
    _safe_json_loads,
    build_turn_request_fingerprint,
)

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
            "t.request_fingerprint, t.revision_of_message_id, t.created_at, t.finished_at, "
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
    fingerprint = request_fingerprint or build_turn_request_fingerprint(content)

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conversation = conn.execute(
                "SELECT user_id, status FROM chat_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not conversation or int(conversation["user_id"]) != int(user_id):
                raise ConversationNotFound("conversation not found")
            if conversation["status"] != "active":
                raise ConversationNotWritable("conversation is not writable")

            existing = conn.execute(
                "SELECT id, conversation_id, user_id, client_request_id, fence, status, "
                "user_message_id, assistant_message_id, request_fingerprint, "
                "revision_of_message_id FROM chat_turns "
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
                    "(id, conversation_id, user_id, client_request_id, fence, status, request_fingerprint) "
                    "VALUES (?, ?, ?, ?, ?, 'running', ?)",
                    (turn_id, conversation_id, user_id, request_id, fence, fingerprint),
                )
                message_cursor = conn.execute(
                    "INSERT INTO chat_messages "
                    "(conversation_id, role, content, token_count, metadata) "
                    "VALUES (?, 'user', ?, 0, ?)",
                    (
                        conversation_id,
                        content,
                        json.dumps(
                            {"turn_id": turn_id, "turn_fence": fence},
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
                    "user_message_id, request_fingerprint) "
                    "VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
                    (
                        turn_id,
                        conversation_id,
                        user_id,
                        request_id,
                        fence,
                        user_message_id,
                        fingerprint,
                    ),
                )
                precreated_metadata.update(
                    {"turn_id": turn_id, "turn_fence": fence}
                )
                conn.execute(
                    "UPDATE chat_messages SET metadata = ? WHERE id = ?",
                    (json.dumps(precreated_metadata, ensure_ascii=False), user_message_id),
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
            )
        except Exception:
            conn.rollback()
            raise


def _load_owned_turn(conn, turn_id: str, conversation_id: str, user_id: int):
    row = conn.execute(
        "SELECT id, conversation_id, user_id, client_request_id, fence, status, "
        "user_message_id, assistant_message_id FROM chat_turns "
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
) -> tuple[ChatTurn, str]:
    """Reserve a new assistant generation without inserting another user message."""
    request_id = str(client_request_id or "").strip()
    if not request_id:
        raise ValueError("client_request_id is required")

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conversation = conn.execute(
                "SELECT user_id, status FROM chat_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if not conversation or int(conversation["user_id"]) != int(user_id):
                raise ConversationNotFound("conversation not found")
            if conversation["status"] != "active":
                raise ConversationNotWritable("conversation is not writable")

            target = conn.execute(
                "SELECT t.user_message_id, t.assistant_message_id, u.content AS user_content "
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
                "user_message_id, request_fingerprint, revision_of_message_id) "
                "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (
                    turn_id,
                    conversation_id,
                    user_id,
                    request_id,
                    fence,
                    target["user_message_id"],
                    fingerprint,
                    assistant_message_id,
                ),
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
) -> ChatTurn:
    """Invalidate a running turn; repeated cancellation is idempotent."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _load_owned_turn(conn, turn_id, conversation_id, user_id)
            if row["status"] == "running":
                conn.execute(
                    "UPDATE chat_turns SET status = 'cancelled', cancel_reason = ?, "
                    "finished_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'running'",
                    (reason[:120], turn_id),
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
) -> None:
    """Reject stale workers before they perform turn-owned side effects."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT t.status, c.status AS conversation_status "
            "FROM chat_turns t JOIN chat_conversations c ON c.id = t.conversation_id "
            "WHERE t.id = ? AND t.fence = ? AND t.conversation_id = ? AND t.user_id = ?",
            (turn_id, fence, conversation_id, user_id),
        ).fetchone()
    if not row:
        raise TurnNotFound("turn not found")
    if row["status"] != "running" or row["conversation_status"] != "active":
        raise TurnCancelled("turn is no longer active")


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
) -> Optional[int]:
    """Persist assistant output only for the still-running turn fence."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT t.status, t.revision_of_message_id, t.request_fingerprint, "
                "c.status AS conversation_status "
                "FROM chat_turns t JOIN chat_conversations c ON c.id = t.conversation_id "
                "WHERE t.id = ? AND t.fence = ? AND t.conversation_id = ? AND t.user_id = ?",
                (turn_id, fence, conversation_id, user_id),
            ).fetchone()
            if not row:
                raise TurnNotFound("turn not found")
            if row["status"] != "running" or row["conversation_status"] != "active":
                raise TurnCancelled("turn is no longer active")

            persisted_metadata = dict(metadata or {})
            persisted_metadata.setdefault("turn_id", turn_id)
            persisted_metadata.setdefault("turn_fence", fence)
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
            updated = conn.execute(
                "UPDATE chat_turns SET status = 'completed', assistant_message_id = ?, "
                "finished_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ? "
                "AND status = 'running'",
                (assistant_id, turn_id, fence, conversation_id, user_id),
            )
            if updated.rowcount != 1:
                raise TurnCancelled("turn is no longer active")

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
) -> None:
    """Mark a still-running turn failed without resurrecting old turns."""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE chat_turns SET status = 'failed', error_code = ?, "
            "finished_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND fence = ? AND conversation_id = ? AND user_id = ? "
            "AND status = 'running'",
            (
                str(error_code or "turn_failed")[:120],
                turn_id,
                fence,
                conversation_id,
                user_id,
            ),
        )
        conn.commit()


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



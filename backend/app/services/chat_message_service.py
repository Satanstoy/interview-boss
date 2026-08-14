"""消息存储服务 - 从 chat_service 机械抽取。

职责:user/assistant 消息的写入(会话归属+active 校验)、读取、分布事件、
会话关联题目 id。

共享原始块来自 chat_common,避免循环依赖。
"""
import json
import logging
from typing import Optional
from app.db.connection import get_db_connection
from app.services.chat_common import (
    ConversationNotFound,
    ConversationNotWritable,
    _safe_json_loads,
)

logger = logging.getLogger("interview-boss")


def _raise_message_write_error(conn, conversation_id: str, user_id: int) -> None:
    row = conn.execute(
        "SELECT user_id, status FROM chat_conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if not row or row["user_id"] != user_id:
        raise ConversationNotFound("conversation not found")
    raise ConversationNotWritable("conversation is not writable")


def save_user_message_if_writable(
    conversation_id: str,
    user_id: int,
    content: str,
    token_count: int = 0,
) -> int:
    """Atomically insert a user message only into an active owned conversation."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_messages "
            "(conversation_id, role, content, token_count, metadata) "
            "SELECT ?, 'user', ?, ?, '{}' "
            "WHERE EXISTS ("
            "SELECT 1 FROM chat_conversations "
            "WHERE id = ? AND user_id = ? AND status = 'active'"
            ")",
            (
                conversation_id,
                content,
                token_count,
                conversation_id,
                user_id,
            ),
        )
        if cursor.rowcount != 1:
            _raise_message_write_error(conn, conversation_id, user_id)

        conn.execute(
            "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ? AND status = 'active'",
            (conversation_id, user_id),
        )
        conn.commit()
        return cursor.lastrowid


def save_assistant_message_if_active(
    conversation_id: str,
    user_id: int,
    content: str,
    token_count: int = 0,
    metadata: Optional[dict] = None,
) -> int:
    """Atomically finalize an assistant message only while the turn is active."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_messages "
            "(conversation_id, role, content, token_count, metadata) "
            "SELECT ?, 'assistant', ?, ?, ? "
            "WHERE EXISTS ("
            "SELECT 1 FROM chat_conversations "
            "WHERE id = ? AND user_id = ? AND status = 'active'"
            ")",
            (
                conversation_id,
                content,
                token_count,
                json.dumps(metadata or {}, ensure_ascii=False),
                conversation_id,
                user_id,
            ),
        )
        if cursor.rowcount != 1:
            _raise_message_write_error(conn, conversation_id, user_id)

        conn.execute(
            "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ? AND status = 'active'",
            (conversation_id, user_id),
        )
        conn.commit()
        return cursor.lastrowid


def save_message(
    conversation_id: str,
    role: str,
    content: str,
    token_count: int = 0,
    metadata: Optional[dict] = None,
) -> int:
    """保存一条消息"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_messages (conversation_id, role, content, token_count, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                token_count,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        # 更新会话的 updated_at
        conn.execute(
            "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        return cursor.lastrowid


def get_messages(conversation_id: str, limit: int = 100) -> list[dict]:
    """获取对话的消息历史"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, role, content, token_count, metadata, created_at "
            "FROM chat_messages "
            "WHERE conversation_id = ? "
            "ORDER BY created_at ASC "
            "LIMIT ?",
            (conversation_id, limit),
        ).fetchall()

    return [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "token_count": row[3],
            "metadata": _safe_json_loads(row[4]),
            "created_at": row[5],
        }
        for row in rows
    ]


def get_distribution_events(conversation_id: str) -> list[dict]:
    """Return every persisted distribution fact without the chat-context limit."""

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT metadata FROM chat_messages "
            "WHERE conversation_id = ? AND role = 'assistant' ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    events: list[dict] = []
    for row in rows:
        metadata = _safe_json_loads(row[0])
        events.extend(
            event
            for event in metadata.get("coverage_events", [])
            if isinstance(event, dict)
        )
        result = metadata.get("distribution_result")
        if isinstance(result, dict):
            events.append({"type": "distribution_result", **result})
    return events


def get_recent_messages(conversation_id: str, limit: int = 10) -> list[dict]:
    """获取最近 N 条消息（用于上下文构建）"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, role, content, token_count, metadata, created_at "
            "FROM chat_messages "
            "WHERE conversation_id = ? "
            "ORDER BY created_at DESC "
            "LIMIT ?",
            (conversation_id, limit),
        ).fetchall()

    # 反转为时间正序
    results = [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "token_count": row[3],
            "metadata": _safe_json_loads(row[4]),
            "created_at": row[5],
        }
        for row in reversed(rows)
    ]
    return results


def get_message_count(conversation_id: str) -> int:
    """获取对话消息总数"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    return row[0] if row else 0


def get_conversation_question_ids(conversation_id: str) -> set[int]:
    """Return question ids already surfaced in a conversation.

    This covers questions used as final basis plus candidate retrieved/drawn
    questions saved in assistant metadata, so later draw calls can avoid repeats.
    """
    ids: set[int] = set()

    def _add(raw_id) -> None:
        try:
            qid = int(raw_id)
        except (TypeError, ValueError):
            return
        if qid > 0:
            ids.add(qid)

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT metadata FROM chat_messages "
            "WHERE conversation_id = ? AND role = 'assistant'",
            (conversation_id,),
        ).fetchall()

    for row in rows:
        meta = _safe_json_loads(row[0])
        for key in ("basis_question_ids",):
            value = meta.get(key)
            if isinstance(value, list):
                for qid in value:
                    _add(qid)

        rerank = meta.get("llm_rerank")
        if isinstance(rerank, dict):
            for key in ("selected_basis_ids",):
                value = rerank.get(key)
                if isinstance(value, list):
                    for qid in value:
                        _add(qid)

        for key in ("retrieved_questions", "selected_basis_questions"):
            value = meta.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _add(item.get("id"))

        plan = meta.get("next_question_plan")
        if isinstance(plan, dict):
            _add(plan.get("question_id"))

    return ids


# ═══════════════════════════════════════════════════
#  用户记忆管理
# ═══════════════════════════════════════════════════



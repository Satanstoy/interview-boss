"""对话业务逻辑 — 会话管理、消息存储、记忆管理"""

import uuid
import json
import logging
import sqlite3
import hashlib
from dataclasses import dataclass
from typing import Optional
from app.db.connection import get_db_connection
from app.agents.chat.coverage_config import get_coverage_thresholds
from app.agents.chat.rhythm_profile import build_rhythm_profile
from app.agents.chat.agent_profile import is_agent_development_position

logger = logging.getLogger("interview-boss")


from app.services.chat_common import (
    ConversationNotFound,
    ConversationNotWritable,
    TurnInProgress,
    TurnCancelled,
    TurnNotFound,
    TurnIdempotencyConflict,
    TurnUserMessageConflict,
    SideEffectConflict,
    SIDE_EFFECT_MAX_ATTEMPTS,
    ChatTurn,
    _chat_turn_from_row,
    build_turn_request_fingerprint,
    _safe_json_loads,
    FLUSH_UTILIZATION_THRESHOLD,
)


from app.services.chat_turn_service import (
    get_chat_turn,
    reserve_chat_turn,
    reserve_chat_revision,
    cancel_chat_turn,
    assert_chat_turn_active,
    finalize_chat_turn,
    fail_chat_turn,
    generate_opening_message,
)

def create_conversation(
    user_id: int,
    mode: str,
    title: Optional[str] = None,
    jd_id: Optional[int] = None,
    resume_text: Optional[str] = None,
    job_position: str = "",
    difficulty: str = "mid",
    experience_id: Optional[int] = None,
    distribution_override: Optional[dict] = None,
    first_message: Optional[str] = None,
    client_request_id: Optional[str] = None,
) -> dict:
    """创建新对话会话"""
    request_id = str(client_request_id or "").strip()
    conv_id = (
        str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"interview-boss:conversation:{user_id}:{request_id}",
            )
        )
        if request_id
        else str(uuid.uuid4())
    )
    if not title:
        title = "新对话" if mode == "free_practice" else "JD定制面试"
    difficulty = difficulty or "mid"
    rhythm_profile = (
        build_rhythm_profile(experience_id, user_id, job_position)
        if experience_id
        else None
    )
    if experience_id and rhythm_profile is None:
        raise ValueError("面经不存在或无权访问")
    thresholds = get_coverage_thresholds(job_position, difficulty, rhythm_profile)
    with get_db_connection() as conn:
        try:
            preference_row = conn.execute(
                "SELECT * FROM user_interview_distribution_preferences WHERE user_id = ? AND job_position = ?",
                (user_id, job_position),
            ).fetchone()
        except sqlite3.OperationalError:
            preference_row = None
        preference = None
        if preference_row:
            preference = {
                "mode": preference_row["mode"],
                "target_question_count": preference_row["target_question_count"],
                "custom_distribution": _safe_json_loads(
                    preference_row["custom_distribution"]
                ),
                "selected_experience_id": preference_row["selected_experience_id"],
                "style_strength": preference_row["style_strength"],
            }
        from app.services.interview_distribution import (
            DistributionStatsUnavailable,
            compile_distribution_plan,
            refresh_distribution_scope,
        )

        try:
            distribution_plan = compile_distribution_plan(
                conn,
                user_id=user_id,
                job_position=job_position,
                request_override=distribution_override,
                preference=preference,
            )
        except (DistributionStatsUnavailable, sqlite3.OperationalError):
            try:
                refresh_distribution_scope(conn, "public_job_position", job_position)
                distribution_plan = compile_distribution_plan(
                    conn,
                    user_id=user_id,
                    job_position=job_position,
                    request_override=distribution_override,
                    preference=preference,
                )
            except sqlite3.OperationalError:
                # Compatibility for historical databases that have not yet run
                # migration 042. Production startup always applies the migration.
                distribution_plan = {
                    "plan_id": str(uuid.uuid4()),
                    "stats_version": None,
                    "source_scope": "legacy",
                    "mode": "system_default",
                    "target_question_count": 10,
                    "distribution": {},
                    "expected_distribution": {},
                    "soft_target_counts": {},
                    "allowed_counts": {},
                    "random_seed": str(uuid.uuid4()),
                    "style_source_snapshot": None,
                }

    interview_config = {
        "difficulty": difficulty,
        "experience_id": experience_id,
        "rhythm_profile_id": f"experience:{experience_id}" if rhythm_profile else None,
        "coverage_thresholds": {
            phase.value: count for phase, count in thresholds.items()
        },
        "rhythm_profile": rhythm_profile or {},
        "distribution_plan": distribution_plan,
        "interview_profile": (
            "agent_development"
            if is_agent_development_position(job_position)
            else None
        ),
    }
    metadata = {"interview_config": interview_config}

    first_message_id = None
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO chat_conversations "
            "(id, user_id, mode, title, jd_id, resume_text, job_position, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conv_id,
                user_id,
                mode,
                title,
                jd_id,
                resume_text,
                job_position,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        if cursor.rowcount == 0:
            existing = conn.execute(
                "SELECT id, user_id, mode, title, job_position, metadata "
                "FROM chat_conversations WHERE id = ? AND user_id = ?",
                (conv_id, user_id),
            ).fetchone()
            if not existing:
                raise ConversationNotFound("conversation not found after idempotent create")
            first_message_row = conn.execute(
                "SELECT id FROM chat_messages WHERE conversation_id = ? "
                "AND role = 'user' ORDER BY id ASC LIMIT 1",
                (conv_id,),
            ).fetchone()
            first_message_id = first_message_row["id"] if first_message_row else None
            conn.commit()
            return {
                "id": existing["id"],
                "mode": existing["mode"],
                "title": existing["title"],
                "job_position": existing["job_position"],
                "metadata": _safe_json_loads(existing["metadata"]),
                "first_message_id": first_message_id,
            }

        if first_message:
            message_cursor = conn.execute(
                "INSERT INTO chat_messages "
                "(conversation_id, role, content, token_count, metadata) "
                "VALUES (?, 'user', ?, 0, ?)",
                (
                    conv_id,
                    first_message,
                    json.dumps({"precreated": True}, ensure_ascii=False),
                ),
            )
            first_message_id = message_cursor.lastrowid
        conn.commit()

    return {
        "id": conv_id,
        "mode": mode,
        "title": title,
        "job_position": job_position,
        "metadata": metadata,
        "first_message_id": first_message_id,
    }


def get_conversations(
    user_id: int, status: str = "active", job_position: str = ""
) -> list[dict]:
    """获取用户的对话列表"""
    with get_db_connection() as conn:
        if job_position:
            rows = conn.execute(
                "SELECT id, mode, title, jd_id, status, created_at, updated_at, job_position "
                "FROM chat_conversations "
                "WHERE user_id = ? AND status = ? AND job_position = ? "
                "ORDER BY updated_at DESC",
                (user_id, status, job_position),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, mode, title, jd_id, status, created_at, updated_at, job_position "
                "FROM chat_conversations "
                "WHERE user_id = ? AND status = ? "
                "ORDER BY updated_at DESC",
                (user_id, status),
            ).fetchall()

    return [
        {
            "id": row[0],
            "mode": row[1],
            "title": row[2],
            "jd_id": row[3],
            "status": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "job_position": row[7],
        }
        for row in rows
    ]


def get_conversation(
    conversation_id: str, user_id: int, job_position: str = ""
) -> Optional[dict]:
    """获取单个对话详情"""
    with get_db_connection() as conn:
        if job_position:
            row = conn.execute(
                "SELECT id, user_id, mode, title, jd_id, resume_text, status, created_at, updated_at, job_position, metadata "
                "FROM chat_conversations WHERE id = ? AND user_id = ? AND job_position = ?",
                (conversation_id, user_id, job_position),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, user_id, mode, title, jd_id, resume_text, status, created_at, updated_at, job_position, metadata "
                "FROM chat_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()

    if not row:
        return None

    metadata = _safe_json_loads(row[10])
    plan = metadata.get("interview_config", {}).get("distribution_plan")
    execution = None
    if isinstance(plan, dict):
        events = get_distribution_events(conversation_id)
        from app.agents.chat.distribution_execution import (
            distribution_execution_from_events,
        )

        execution = distribution_execution_from_events(plan, events)

    return {
        "id": row[0],
        "user_id": row[1],
        "mode": row[2],
        "title": row[3],
        "jd_id": row[4],
        "resume_text": row[5],
        "status": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "job_position": row[9],
        "metadata": metadata,
        "distribution_execution": execution,
    }


def update_conversation_title(conversation_id: str, title: str) -> None:
    """更新对话标题"""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE chat_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, conversation_id),
        )
        conn.commit()


def archive_conversation(
    conversation_id: str, user_id: int, job_position: str = ""
) -> bool:
    """归档对话"""
    with get_db_connection() as conn:
        if job_position:
            cursor = conn.execute(
                "UPDATE chat_conversations SET status = 'archived', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ? AND job_position = ?",
                (conversation_id, user_id, job_position),
            )
        else:
            cursor = conn.execute(
                "UPDATE chat_conversations SET status = 'archived', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
        conn.commit()
        return cursor.rowcount > 0


def delete_conversation(
    conversation_id: str, user_id: int, job_position: str = ""
) -> bool:
    """删除对话（级联删除消息）

    注意：删除操作只检查 user_id 和 conversation_id，不检查 job_position。
    用户应该能删除自己创建的任何对话，不管当前岗位是什么。
    """
    with get_db_connection() as conn:
        # 先清理没有外键约束的关联表
        conn.execute(
            "DELETE FROM chat_tool_traces WHERE conversation_id = ?", (conversation_id,)
        )
        conn.execute(
            "DELETE FROM interview_asked_questions WHERE conversation_id = ? AND user_id = ?",
            (conversation_id, user_id),
        )

        # 删除对话（chat_messages 会通过 ON DELETE CASCADE 自动删除）
        cursor = conn.execute(
            "DELETE FROM chat_conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_conversation_metadata(
    conversation_id: str,
    new_metadata: dict,
    *,
    expected_version: int | None = None,
    user_id: int | None = None,
) -> int:
    """Merge metadata with an optimistic version check and return its new version."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT metadata, metadata_version, user_id FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row or (user_id is not None and int(row["user_id"]) != int(user_id)):
            conn.rollback()
            raise ConversationNotFound("conversation not found")
        current_version = int(row["metadata_version"] or 0)
        if expected_version is not None and int(expected_version) != current_version:
            conn.rollback()
            raise SideEffectConflict("conversation_metadata", current_version)
        existing = _safe_json_loads(row["metadata"])
        existing.update(new_metadata or {})
        next_version = current_version + 1
        updated = conn.execute(
            "UPDATE chat_conversations SET metadata = ?, metadata_version = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND metadata_version = ?",
            (
                json.dumps(existing, ensure_ascii=False),
                next_version,
                conversation_id,
                current_version,
            ),
        )
        if updated.rowcount != 1:
            conn.rollback()
            raise SideEffectConflict("conversation_metadata", current_version)
        conn.commit()
        return next_version


def get_conversation_metadata(conversation_id: str) -> dict:
    """Get the conversation's metadata JSON field."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT metadata FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return _safe_json_loads(row[0]) if row else {}


def get_conversation_metadata_snapshot(conversation_id: str) -> dict:
    """Return metadata plus its optimistic-concurrency version."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT metadata, metadata_version FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return {
        "metadata": _safe_json_loads(row["metadata"]) if row else {},
        "version": int(row["metadata_version"] or 0) if row else 0,
    }


# ═══════════════════════════════════════════════════
#  消息管理
# ═══════════════════════════════════════════════════


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


def save_memory(
    user_id: int,
    memory_type: str,
    content: str,
    source: str = "auto_extract",
    summary: str = "",
    *,
    source_turn_id: str | None = None,
    source_job_id: str | None = None,
    memory_schema_version: int = 1,
    expires_at: str | None = None,
) -> int:
    """保存一条带 provenance 的用户记忆，并按 content hash 幂等去重。"""
    content = str(content or "").strip()
    if not content:
        raise ValueError("memory content is required")
    if memory_type not in {"weakness", "strength", "preference", "resume", "topic"}:
        raise ValueError("unsupported memory type")
    if not summary:
        summary = content[:77] + "..." if len(content) > 80 else content
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM chat_memories WHERE user_id = ? AND content_hash = ? "
            "AND is_active = 1 AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) LIMIT 1",
            (user_id, content_hash),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cursor = conn.execute(
            "INSERT INTO chat_memories "
            "(user_id, memory_type, content, source, summary, source_turn_id, source_job_id, "
            "memory_schema_version, expires_at, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                memory_type,
                content,
                source,
                summary,
                source_turn_id,
                source_job_id,
                int(memory_schema_version),
                expires_at,
                content_hash,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_memories(user_id: int, memory_type: Optional[str] = None) -> list[dict]:
    """获取用户的长期记忆"""
    with get_db_connection() as conn:
        if memory_type:
            rows = conn.execute(
                "SELECT id, memory_type, content, source, created_at "
                "FROM chat_memories WHERE user_id = ? AND memory_type = ? AND is_active = 1 "
                "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) "
                "ORDER BY updated_at DESC",
                (user_id, memory_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, memory_type, content, source, created_at "
                "FROM chat_memories WHERE user_id = ? AND is_active = 1 "
                "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) "
                "ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()

    return [
        {
            "id": row[0],
            "memory_type": row[1],
            "content": row[2],
            "source": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def deactivate_memory(memory_id: int, user_id: int) -> bool:
    """停用一条记忆"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE chat_memories SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (memory_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_memory_summaries(user_id: int, limit: int = 5) -> list[dict]:
    """获取用户记忆摘要（轻量级，用于 prompt 注入）"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, memory_type, summary, updated_at "
            "FROM chat_memories WHERE user_id = ? AND is_active = 1 AND memory_type != 'resume' "
            "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [
        {"id": r[0], "memory_type": r[1], "summary": r[2], "updated_at": r[3]}
        for r in rows
    ]


def get_memories_by_ids(memory_ids: list[int], user_id: int) -> list[dict]:
    """按 ID 列表获取记忆完整内容（按需加载）"""
    if not memory_ids:
        return []
    placeholders = ",".join("?" * len(memory_ids))
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT id, memory_type, content, source, created_at "
            f"FROM chat_memories WHERE id IN ({placeholders}) AND user_id = ? AND is_active = 1 "
            "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
            list(memory_ids) + [user_id],
        ).fetchall()
    return [
        {
            "id": r[0],
            "memory_type": r[1],
            "content": r[2],
            "source": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


def get_topic_memories(user_id: int, keywords: list[str], limit: int = 5) -> list[dict]:
    """按话题关键词匹配记忆，无匹配时回退到最近记忆"""
    if not keywords:
        return get_memory_summaries(user_id, limit=limit)

    with get_db_connection() as conn:
        conditions = []
        params = [user_id]
        for kw in keywords[:5]:
            kw = kw.strip()
            if kw:
                conditions.append("content LIKE ?")
                params.append(f"%{kw}%")

        if not conditions:
            return get_memory_summaries(user_id, limit=limit)

        where_clause = " OR ".join(conditions)
        rows = conn.execute(
            f"SELECT id, memory_type, summary, updated_at "
            f"FROM chat_memories "
            f"WHERE user_id = ? AND is_active = 1 AND memory_type != 'resume' "
            "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) "
            f"AND ({where_clause}) "
            f"ORDER BY updated_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()

    if not rows:
        return get_memory_summaries(user_id, limit=limit)

    return [
        {"id": r[0], "memory_type": r[1], "summary": r[2], "updated_at": r[3]}
        for r in rows
    ]


def get_resume_memory(user_id: int) -> Optional[str]:
    """获取用户的简历记忆（最新的 active 简历）"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT content FROM chat_memories "
            "WHERE user_id = ? AND memory_type = 'resume' AND is_active = 1 "
            "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return row[0] if row else None


def save_resume_memory(user_id: int, resume_text: str) -> int:
    """保存或更新用户的简历记忆（停用旧的，创建新的）"""
    with get_db_connection() as conn:
        # 去重：相同内容已存在则跳过
        existing = conn.execute(
            "SELECT id FROM chat_memories "
            "WHERE user_id = ? AND memory_type = 'resume' AND is_active = 1 AND content = ?",
            (user_id, resume_text),
        ).fetchone()
        if existing:
            return existing[0]

        # 停用旧简历
        conn.execute(
            "UPDATE chat_memories SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ? AND memory_type = 'resume' AND is_active = 1",
            (user_id,),
        )
        cursor = conn.execute(
            "INSERT INTO chat_memories (user_id, memory_type, content, source) "
            "VALUES (?, 'resume', ?, 'user_upload')",
            (user_id, resume_text),
        )
        conn.commit()
        return cursor.lastrowid


# ═══════════════════════════════════════════════════
#  会话级 Session Notes（增量记忆）
# ═══════════════════════════════════════════════════


def get_session_notes(conversation_id: str) -> str:
    """获取会话的累积 session notes"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT session_notes FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return row[0] if row and row[0] else ""


def get_session_notes_snapshot(conversation_id: str) -> dict:
    """Return session notes together with its optimistic version."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT session_notes, session_notes_version FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return {
        "notes": row["session_notes"] if row and row["session_notes"] else "",
        "version": int(row["session_notes_version"] or 0) if row else 0,
    }


def update_session_notes(
    conversation_id: str,
    notes: str,
    *,
    expected_version: int | None = None,
) -> int:
    """更新 session notes with an optimistic version check."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT session_notes_version FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            conn.rollback()
            raise ConversationNotFound("conversation not found")
        current_version = int(row["session_notes_version"] or 0)
        if expected_version is not None and int(expected_version) != current_version:
            conn.rollback()
            raise SideEffectConflict("session_notes", current_version)
        next_version = current_version + 1
        updated = conn.execute(
            "UPDATE chat_conversations SET session_notes = ?, session_notes_version = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND session_notes_version = ?",
            (notes, next_version, conversation_id, current_version),
        )
        if updated.rowcount != 1:
            conn.rollback()
            raise SideEffectConflict("session_notes", current_version)
        conn.commit()
        return next_version


# ═══════════════════════════════════════════════════
#  Pre-compaction 记忆刷盘（OpenClaw: flush before discard）
# ═══════════════════════════════════════════════════



def flush_needed(session_notes: str, utilization_pct: float) -> bool:
    """判断是否需要 pre-compaction 记忆刷盘

    OpenClaw 设计哲学：在上下文压缩丢弃信息前，先将重要记忆持久化。
    触发条件：高利用率 + 有未持久化的 session notes。

    Returns:
        True 如果需要刷盘
    """
    if not session_notes or not session_notes.strip():
        return False
    return utilization_pct >= FLUSH_UTILIZATION_THRESHOLD


def flush_session_to_memories(user_id: int, session_notes: str) -> int:
    """从 session notes 提取记忆并保存到 memories 表

    解析 [weakness]/[strength]/[topics] 标签，跳过 [pending] 和 [asked]。

    Returns:
        保存的记忆条数
    """
    if not session_notes or not session_notes.strip():
        return 0

    import re

    saved = 0

    # 已存在的记忆内容（用于去重）
    existing = get_memories(user_id)
    existing_contents = {m["content"] for m in existing}

    for line in session_notes.split("\n"):
        line = line.strip()
        if not line:
            continue

        # 跳过临时标签
        if line.startswith("[pending]") or line.startswith("[asked]"):
            continue

        match = re.match(r"\[(weakness|strength|topics|preference)\]\s*(.*)", line)
        if not match:
            continue

        tag = match.group(1)
        content = match.group(2).strip()
        if not content or content in existing_contents:
            continue

        memory_type = tag if tag != "topics" else "preference"
        save_memory(user_id, memory_type, content, source="session_flush")
        existing_contents.add(content)
        saved += 1

    return saved


# ═══════════════════════════════════════════════════
#  跨对话会话搜索（Hermes: session_search + FTS5）
# ═══════════════════════════════════════════════════


def search_past_sessions(
    user_id: int,
    keywords: list[str],
    limit: int = 3,
    exclude_conv_id: Optional[str] = None,
    job_position: str = "",
) -> list[dict]:
    """搜索用户历史对话中的相关面试经验

    使用 chat_messages 表的 LIKE 搜索匹配关键词，
    返回包含匹配消息的对话摘要。

    Returns:
        [{conversation_id, title, summary, created_at}, ...]
    """
    if not keywords:
        return []

    with get_db_connection() as conn:
        # 构建关键词 LIKE 条件
        conditions = []
        params = [user_id]
        for kw in keywords[:5]:
            kw = kw.strip()
            if kw:
                conditions.append("m.content LIKE ?")
                params.append(f"%{kw}%")

        if not conditions:
            return []

        where_likes = " OR ".join(conditions)
        position_clause = "AND c.job_position = ?" if job_position else ""
        if job_position:
            params.append(job_position)
        exclude_clause = "AND c.id != ?" if exclude_conv_id else ""
        if exclude_conv_id:
            params.append(exclude_conv_id)

        params.append(limit)

        rows = conn.execute(
            f"SELECT DISTINCT c.id, c.title, c.created_at, "
            f"SUBSTR(m.content, 1, 120) as snippet "
            f"FROM chat_conversations c "
            f"JOIN chat_messages m ON m.conversation_id = c.id "
            f"WHERE c.user_id = ? AND c.status = 'active' "
            f"AND ({where_likes}) {position_clause} {exclude_clause} "
            f"ORDER BY c.updated_at DESC "
            f"LIMIT ?",
            params,
        ).fetchall()

    return [
        {
            "conversation_id": r[0],
            "title": r[1] or "未命名对话",
            "summary": r[3] or "",
            "created_at": r[2],
        }
        for r in rows
    ]


def format_session_recall(sessions: list[dict]) -> str:
    """将搜索结果格式化为可注入上下文的文本

    Returns:
        格式化的文本，如:
        【历史面试经验】
        - [2026-05-20] Redis 面试: 讨论了缓存策略...
    """
    if not sessions:
        return ""

    lines = ["【历史面试经验】"]
    for s in sessions:
        date = s.get("created_at", "")[:10]
        title = s.get("title", "未命名")
        summary = s.get("summary", "")[:80]
        lines.append(f"- [{date}] {title}: {summary}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════
#  Durable side effects / structured turn ledger
# ═══════════════════════════════════════════════════


def _side_effect_job_dict(row) -> dict:
    payload = {}
    try:
        parsed = json.loads(row["payload_json"] or "{}")
        payload = parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    result = dict(row)
    result["payload"] = payload
    result.pop("payload_json", None)
    return result


def get_side_effect_job(job_id: str, user_id: int | None = None) -> dict | None:
    with get_db_connection() as conn:
        where = ["id = ?"]
        params: list[object] = [job_id]
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        row = conn.execute(
            "SELECT id, kind, user_id, conversation_id, source_turn_id, payload_json, status, "
            "attempts, available_at, locked_at, finished_at, last_error, created_at "
            "FROM chat_side_effect_jobs WHERE " + " AND ".join(where),
            params,
        ).fetchone()
    return _side_effect_job_dict(row) if row else None


def claim_side_effect_job(
    *,
    worker_id: str,
    kind: str | None = None,
    source_turn_id: str | None = None,
) -> dict | None:
    """Claim one ready job; the claim is durable across worker restarts."""
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        where = [
            "status IN ('pending', 'failed')",
            "available_at <= CURRENT_TIMESTAMP",
        ]
        params: list[object] = []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if source_turn_id:
            where.append("source_turn_id = ?")
            params.append(source_turn_id)
        row = conn.execute(
            "SELECT id FROM chat_side_effect_jobs WHERE " + " AND ".join(where) + " "
            "ORDER BY available_at ASC, created_at ASC LIMIT 1",
            params,
        ).fetchone()
        if not row:
            conn.rollback()
            return None
        updated = conn.execute(
            "UPDATE chat_side_effect_jobs SET status = 'running', attempts = attempts + 1, "
            "locked_at = CURRENT_TIMESTAMP, last_error = NULL WHERE id = ? "
            "AND status IN ('pending', 'failed')",
            (row["id"],),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
    job = get_side_effect_job(row["id"])
    if job:
        job["worker_id"] = worker_id
    return job


def complete_side_effect_job(job_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE chat_side_effect_jobs SET status = 'completed', "
            "finished_at = CURRENT_TIMESTAMP, locked_at = NULL "
            "WHERE id = ? AND status = 'running'",
            (job_id,),
        )
        conn.commit()
        return cursor.rowcount == 1


def fail_side_effect_job(job_id: str, error: str, *, retry: bool = True) -> bool:
    """Retry transient failures with bounded exponential backoff."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT attempts FROM chat_side_effect_jobs WHERE id = ? AND status = 'running'",
            (job_id,),
        ).fetchone()
        if not row:
            return False
        attempts = int(row["attempts"] or 0)
        terminal = not retry or attempts >= SIDE_EFFECT_MAX_ATTEMPTS
        status = "dead_letter" if terminal else "failed"
        delay = min(300, 2 ** max(0, attempts - 1))
        conn.execute(
            "UPDATE chat_side_effect_jobs SET status = ?, last_error = ?, locked_at = NULL, "
            "finished_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, "
            "available_at = CASE WHEN ? THEN available_at ELSE datetime('now', ?) END "
            "WHERE id = ?",
            (
                status,
                str(error or "side_effect_failed")[:500],
                terminal,
                terminal,
                f"+{delay} seconds",
                job_id,
            ),
        )
        conn.commit()
        return True


def commit_memory_extraction_job(
    job_id: str,
    memories: list[dict],
    note_parts: list[str],
) -> dict:
    """Validate and atomically persist extracted memories plus session notes."""
    allowed_types = {"weakness", "strength", "preference", "topic"}
    accepted: list[dict] = []
    for item in memories or []:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("type") or "").strip()
        content = str(item.get("content") or "").strip()
        if memory_type not in allowed_types or not content or len(content) > 500:
            continue
        accepted.append({"type": memory_type, "content": content})

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute(
            "SELECT * FROM chat_side_effect_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not job:
            conn.rollback()
            raise LookupError("side-effect job not found")
        if job["status"] == "completed":
            conn.rollback()
            return {"status": "completed", "memory_count": 0, "notes_updated": False}
        if job["status"] != "running":
            conn.rollback()
            raise SideEffectConflict("side_effect_job")
        source_turn = conn.execute(
            "SELECT status FROM chat_turns WHERE id = ? AND conversation_id = ? AND user_id = ?",
            (job["source_turn_id"], job["conversation_id"], job["user_id"]),
        ).fetchone()
        if not source_turn or source_turn["status"] != "completed":
            conn.execute(
                "UPDATE chat_side_effect_jobs SET status = 'skipped', finished_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (job_id,),
            )
            conn.commit()
            return {"status": "skipped", "memory_count": 0, "notes_updated": False}

        memory_count = 0
        for item in accepted:
            content = item["content"]
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            exists = conn.execute(
                "SELECT id FROM chat_memories WHERE user_id = ? AND content_hash = ? "
                "AND is_active = 1 AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)",
                (job["user_id"], content_hash),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO chat_memories (user_id, memory_type, content, source, summary, "
                "source_turn_id, source_job_id, memory_schema_version, content_hash) "
                "VALUES (?, ?, ?, 'auto_extract', ?, ?, ?, 1, ?)",
                (
                    job["user_id"],
                    item["type"],
                    content,
                    content[:77] + "..." if len(content) > 80 else content,
                    job["source_turn_id"],
                    job_id,
                    content_hash,
                ),
            )
            memory_count += 1

        notes_updated = False
        notes = [str(note).strip() for note in note_parts or [] if str(note).strip()]
        if notes:
            conversation = conn.execute(
                "SELECT session_notes, session_notes_version FROM chat_conversations "
                "WHERE id = ? AND user_id = ?",
                (job["conversation_id"], job["user_id"]),
            ).fetchone()
            if not conversation:
                conn.rollback()
                raise ConversationNotFound("conversation not found")
            current = conversation["session_notes"] or ""
            combined = "\n".join(part for part in (current, "\n".join(notes)) if part)
            if len(combined) > 2000:
                combined = "\n".join(combined.splitlines()[-80:])[-2000:]
            version = int(conversation["session_notes_version"] or 0)
            updated = conn.execute(
                "UPDATE chat_conversations SET session_notes = ?, session_notes_version = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? "
                "AND session_notes_version = ?",
                (
                    combined,
                    version + 1,
                    job["conversation_id"],
                    job["user_id"],
                    version,
                ),
            )
            if updated.rowcount != 1:
                conn.rollback()
                raise SideEffectConflict("session_notes", version)
            notes_updated = True

        conn.execute(
            "UPDATE chat_side_effect_jobs SET status = 'completed', finished_at = CURRENT_TIMESTAMP, "
            "locked_at = NULL WHERE id = ? AND status = 'running'",
            (job_id,),
        )
        conn.commit()
    return {
        "status": "completed",
        "memory_count": memory_count,
        "notes_updated": notes_updated,
    }


def create_candidate_set(
    *,
    user_id: int,
    conversation_id: str,
    source: str,
    items: list[dict],
    expires_at: str,
    source_turn_id: str | None = None,
    schema_version: int = 1,
) -> str:
    """Persist a server-owned candidate set containing references, not authority text."""
    normalized = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        try:
            question_id = int(item.get("id", item.get("question_id")))
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "question_id": question_id,
                "rank": int(item.get("rank", index)),
                "source": str(item.get("source") or source),
            }
        )
    candidate_set_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO chat_candidate_sets "
            "(id, user_id, conversation_id, source, source_turn_id, items_json, schema_version, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                candidate_set_id,
                user_id,
                conversation_id,
                source,
                source_turn_id,
                json.dumps(normalized, ensure_ascii=False),
                schema_version,
                expires_at,
            ),
        )
        conn.commit()
    return candidate_set_id


def get_candidate_set(
    candidate_set_id: str, user_id: int, conversation_id: str
) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM chat_candidate_sets WHERE id = ? AND user_id = ? AND conversation_id = ?",
            (candidate_set_id, user_id, conversation_id),
        ).fetchone()
        if not row:
            return None
        if (
            row["status"] == "available"
            and row["expires_at"]
            <= conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
        ):
            conn.execute(
                "UPDATE chat_candidate_sets SET status = 'expired' WHERE id = ?",
                (candidate_set_id,),
            )
            conn.commit()
            return None
    try:
        items = json.loads(row["items_json"] or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        items = []
    result = dict(row)
    result["items"] = items if isinstance(items, list) else []
    result.pop("items_json", None)
    return result


def consume_candidate_set(
    candidate_set_id: str,
    *,
    user_id: int,
    conversation_id: str,
    selected_item_id: int,
) -> dict:
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM chat_candidate_sets WHERE id = ? AND user_id = ? AND conversation_id = ?",
            (candidate_set_id, user_id, conversation_id),
        ).fetchone()
        if not row:
            conn.rollback()
            raise LookupError("candidate set not found")
        if (
            row["status"] != "available"
            or row["expires_at"]
            <= conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
        ):
            conn.execute(
                "UPDATE chat_candidate_sets SET status = 'expired' WHERE id = ? AND status = 'available'",
                (candidate_set_id,),
            )
            conn.commit()
            raise ValueError("candidate set is unavailable")
        items = json.loads(row["items_json"] or "[]")
        selected = next(
            (
                item
                for item in items
                if int(item.get("question_id", 0)) == int(selected_item_id)
            ),
            None,
        )
        if not selected:
            conn.rollback()
            raise ValueError("selected question is not in candidate set")
        conn.execute(
            "UPDATE chat_candidate_sets SET status = 'consumed', selected_item_id = ?, "
            "consumed_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'available'",
            (selected_item_id, candidate_set_id),
        )
        conn.commit()
    return selected


def resolve_candidate_question(
    candidate_set_id: str,
    *,
    user_id: int,
    conversation_id: str,
    selected_item_id: int,
) -> dict:
    """Consume a candidate reference, then reload authoritative question content."""
    selected = consume_candidate_set(
        candidate_set_id,
        user_id=user_id,
        conversation_id=conversation_id,
        selected_item_id=selected_item_id,
    )
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, question, cat1, cat2, tags, difficulty, sources "
            "FROM question_bank WHERE id = ? AND deleted_at IS NULL AND status = 'approved'",
            (selected["question_id"],),
        ).fetchone()
    if not row:
        raise LookupError("candidate question is no longer authoritative")
    return dict(row)


def append_interview_event(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    event_key: str,
    event_type: str,
    payload: dict,
    schema_version: int = 1,
) -> int:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO interview_events "
            "(user_id, conversation_id, turn_id, event_key, event_type, payload_json, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                conversation_id,
                turn_id,
                event_key,
                event_type,
                json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                schema_version,
            ),
        )
        conn.commit()
        if cursor.rowcount:
            return int(cursor.lastrowid)
        row = conn.execute(
            "SELECT id FROM interview_events WHERE turn_id = ? AND event_key = ?",
            (turn_id, event_key),
        ).fetchone()
        return int(row["id"])


def get_interview_events(
    conversation_id: str, user_id: int | None = None
) -> list[dict]:
    with get_db_connection() as conn:
        where = ["conversation_id = ?"]
        params: list[object] = [conversation_id]
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        rows = conn.execute(
            "SELECT id, user_id, conversation_id, turn_id, event_key, event_type, "
            "payload_json, schema_version, created_at FROM interview_events WHERE "
            + " AND ".join(where)
            + " ORDER BY id ASC",
            params,
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        try:
            payload = json.loads(item.pop("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        item["payload"] = payload if isinstance(payload, dict) else {}
        events.append(item)
    return events


def fold_interview_events(events: list[dict]) -> dict:
    """Fold domain events into a deterministic lifecycle/coverage read model."""
    state = "technical"
    coverage: dict[str, int] = {}
    last_turn_id = None
    transitions = {
        "technical": {"candidate_question", "final_summary", "closed"},
        "candidate_question": {"final_summary", "closed"},
        "final_summary": {"closed"},
        "closed": set(),
    }
    for event in events or []:
        payload = event.get("payload") if isinstance(event, dict) else {}
        payload = payload if isinstance(payload, dict) else {}
        last_turn_id = event.get("turn_id") or last_turn_id
        if event.get("event_type") == "coverage":
            phase = str(payload.get("phase") or "").strip()
            if payload.get("counts_toward_target") is True and phase:
                coverage[phase] = coverage.get(phase, 0) + 1
        elif event.get("event_type") == "state_transition":
            target = str(payload.get("to") or "")
            if target in transitions.get(state, set()):
                state = target
    return {"state": state, "coverage": coverage, "last_turn_id": last_turn_id}


def record_assistant_generation(
    *,
    user_id: int,
    conversation_id: str,
    turn_id: str,
    message_id: int,
    source_turn_id: str,
    contract_hash: str = "",
    evidence_refs: list[str] | None = None,
    parent_generation_id: str | None = None,
) -> str:
    generation_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        if parent_generation_id is None:
            parent = conn.execute(
                "SELECT id FROM assistant_generations WHERE conversation_id = ? AND visible = 1 "
                "ORDER BY created_at DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            parent_generation_id = parent["id"] if parent else None
        conn.execute(
            "UPDATE assistant_generations SET visible = 0 WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.execute(
            "INSERT INTO assistant_generations "
            "(id, user_id, conversation_id, turn_id, message_id, parent_generation_id, "
            "source_turn_id, contract_hash, evidence_refs_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                generation_id,
                user_id,
                conversation_id,
                turn_id,
                message_id,
                parent_generation_id,
                source_turn_id,
                contract_hash,
                json.dumps(evidence_refs or [], ensure_ascii=False),
            ),
        )
        conn.commit()
    return generation_id


def get_current_assistant_generation(conversation_id: str, user_id: int) -> dict | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM assistant_generations WHERE conversation_id = ? AND user_id = ? "
            "AND visible = 1 ORDER BY created_at DESC LIMIT 1",
            (conversation_id, user_id),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["evidence_refs"] = json.loads(result.pop("evidence_refs_json") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        result["evidence_refs"] = []
    return result

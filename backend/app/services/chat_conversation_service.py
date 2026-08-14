"""会话(conversation)服务 - 从 chat_service 机械抽取。

职责:会话的创建/列表/详情/标题/归档/删除、元数据读写与快照。

依赖 chat_common 共享原始块;get_distribution_events 来自 chat_message_service。
"""
import json
import sqlite3
import uuid
import logging
from typing import Optional
from app.agents.chat.coverage_config import get_coverage_thresholds
from app.agents.chat.rhythm_profile import build_rhythm_profile
from app.agents.chat.agent_profile import is_agent_development_position
from app.db.connection import get_db_connection
from app.services.chat_common import (
    ConversationNotFound,
    SideEffectConflict,
    _safe_json_loads,
)
from app.services.chat_message_service import get_distribution_events

logger = logging.getLogger("interview-boss")


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



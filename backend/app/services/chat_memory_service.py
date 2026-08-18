"""记忆服务 - 从 chat_service 机械抽取。

职责:用户长期记忆(会话级 memory)、主题记忆、简历记忆的存取与失效。

共享原始块来自 chat_common,避免循环依赖。
"""
import logging
import hashlib
from typing import Optional
from app.db.connection import get_db_connection

logger = logging.getLogger("interview-boss")


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


def deactivate_resume_memories(user_id: int) -> int:
    """停用用户所有 active 简历记忆（profile save/delete 时同步清理）。

    audit D9 / spec Task A：user_resumes 与 chat_memories 的简历副本必须同步，
    删除/替换简历后旧副本不得继续被面试 agent 召回（含已删简历的 PII）。
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE chat_memories SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ? AND memory_type = 'resume' AND is_active = 1",
            (user_id,),
        )
        conn.commit()
        return cursor.rowcount


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



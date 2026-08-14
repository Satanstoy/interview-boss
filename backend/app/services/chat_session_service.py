"""会话笔记与刷盘服务 - 从 chat_service 机械抽取。

职责:session notes 读写、长度利用触发刷盘、会话级记忆落库、跨会话召回与格式化。

依赖 chat_common 共享原始块;get_memories/save_memory 来自 chat_memory_service。
"""
import logging
from typing import Optional
from app.db.connection import get_db_connection
from app.services.chat_common import (
    ConversationNotFound,
    SideEffectConflict,
    FLUSH_UTILIZATION_THRESHOLD,
)
from app.services.chat_memory_service import get_memories, save_memory

logger = logging.getLogger("interview-boss")


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



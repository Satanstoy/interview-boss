"""对话业务逻辑 — 会话管理、消息存储、记忆管理"""
import uuid
import json
import logging
from typing import Optional
from app.db.connection import get_db_connection

logger = logging.getLogger("interview-boss")


def _safe_json_loads(raw) -> dict:
    """安全解析 JSON 字符串，解析失败返回空字典"""
    if not raw or not str(raw).strip():
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


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

def create_conversation(
    user_id: int,
    mode: str,
    title: Optional[str] = None,
    jd_id: Optional[int] = None,
    resume_text: Optional[str] = None,
) -> dict:
    """创建新对话会话"""
    conv_id = str(uuid.uuid4())
    if not title:
        title = "新对话" if mode == "free_practice" else "JD定制面试"

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO chat_conversations (id, user_id, mode, title, jd_id, resume_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, user_id, mode, title, jd_id, resume_text)
        )
        conn.commit()

    return {"id": conv_id, "mode": mode, "title": title}


def get_conversations(user_id: int, status: str = "active") -> list[dict]:
    """获取用户的对话列表"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, mode, title, jd_id, status, created_at, updated_at "
            "FROM chat_conversations "
            "WHERE user_id = ? AND status = ? "
            "ORDER BY updated_at DESC",
            (user_id, status)
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
        }
        for row in rows
    ]


def get_conversation(conversation_id: str, user_id: int) -> Optional[dict]:
    """获取单个对话详情"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, user_id, mode, title, jd_id, resume_text, status, created_at, updated_at "
            "FROM chat_conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id)
        ).fetchone()

    if not row:
        return None

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
    }


def update_conversation_title(conversation_id: str, title: str) -> None:
    """更新对话标题"""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE chat_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, conversation_id)
        )
        conn.commit()


def archive_conversation(conversation_id: str, user_id: int) -> bool:
    """归档对话"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE chat_conversations SET status = 'archived', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (conversation_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_conversation(conversation_id: str, user_id: int) -> bool:
    """删除对话（级联删除消息）"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM chat_conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def update_conversation_metadata(conversation_id: str, new_metadata: dict) -> None:
    """Merge new_metadata into the conversation's metadata JSON column.

    Reads existing metadata, merges new keys (shallow), and writes back.
    NOTE: Shallow merge only — top-level keys in new_metadata overwrite existing
    values. If nested structures are needed in the future, switch to deep merge.
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT metadata FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        existing = _safe_json_loads(row[0]) if row else {}
        existing.update(new_metadata)
        conn.execute(
            "UPDATE chat_conversations SET metadata = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(existing, ensure_ascii=False), conversation_id),
        )
        conn.commit()


def get_conversation_metadata(conversation_id: str) -> dict:
    """Get the conversation's metadata JSON field."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT metadata FROM chat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return _safe_json_loads(row[0]) if row else {}


# ═══════════════════════════════════════════════════
#  消息管理
# ═══════════════════════════════════════════════════

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
            (conversation_id, role, content, token_count, json.dumps(metadata or {}, ensure_ascii=False))
        )
        # 更新会话的 updated_at
        conn.execute(
            "UPDATE chat_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,)
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
            (conversation_id, limit)
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


def get_recent_messages(conversation_id: str, limit: int = 10) -> list[dict]:
    """获取最近 N 条消息（用于上下文构建）"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, role, content, token_count, metadata, created_at "
            "FROM chat_messages "
            "WHERE conversation_id = ? "
            "ORDER BY created_at DESC "
            "LIMIT ?",
            (conversation_id, limit)
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
            (conversation_id,)
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
) -> int:
    """保存一条用户记忆"""
    if not summary:
        summary = content[:77] + "..." if len(content) > 80 else content
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_memories (user_id, memory_type, content, source, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, memory_type, content, source, summary)
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
                "ORDER BY updated_at DESC",
                (user_id, memory_type)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, memory_type, content, source, created_at "
                "FROM chat_memories WHERE user_id = ? AND is_active = 1 "
                "ORDER BY updated_at DESC",
                (user_id,)
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
            (memory_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_memory_summaries(user_id: int, limit: int = 5) -> list[dict]:
    """获取用户记忆摘要（轻量级，用于 prompt 注入）"""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, memory_type, summary, updated_at "
            "FROM chat_memories WHERE user_id = ? AND is_active = 1 AND memory_type != 'resume' "
            "ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit)
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
            f"FROM chat_memories WHERE id IN ({placeholders}) AND user_id = ? AND is_active = 1",
            list(memory_ids) + [user_id]
        ).fetchall()
    return [
        {"id": r[0], "memory_type": r[1], "content": r[2], "source": r[3], "created_at": r[4]}
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
            f"AND ({where_clause}) "
            f"ORDER BY updated_at DESC LIMIT ?",
            params + [limit]
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
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    return row[0] if row else None


def save_resume_memory(user_id: int, resume_text: str) -> int:
    """保存或更新用户的简历记忆（停用旧的，创建新的）"""
    with get_db_connection() as conn:
        # 去重：相同内容已存在则跳过
        existing = conn.execute(
            "SELECT id FROM chat_memories "
            "WHERE user_id = ? AND memory_type = 'resume' AND is_active = 1 AND content = ?",
            (user_id, resume_text)
        ).fetchone()
        if existing:
            return existing[0]

        # 停用旧简历
        conn.execute(
            "UPDATE chat_memories SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ? AND memory_type = 'resume' AND is_active = 1",
            (user_id,)
        )
        cursor = conn.execute(
            "INSERT INTO chat_memories (user_id, memory_type, content, source) "
            "VALUES (?, 'resume', ?, 'user_upload')",
            (user_id, resume_text)
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
            (conversation_id,)
        ).fetchone()
    return row[0] if row and row[0] else ""


def update_session_notes(conversation_id: str, notes: str) -> None:
    """更新会话的 session notes"""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE chat_conversations SET session_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (notes, conversation_id)
        )
        conn.commit()


# ═══════════════════════════════════════════════════
#  Pre-compaction 记忆刷盘（OpenClaw: flush before discard）
# ═══════════════════════════════════════════════════

# 刷盘触发阈值
FLUSH_UTILIZATION_THRESHOLD = 80.0


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

        match = re.match(r'\[(weakness|strength|topics|preference)\]\s*(.*)', line)
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
            f"AND ({where_likes}) {exclude_clause} "
            f"ORDER BY c.updated_at DESC "
            f"LIMIT ?",
            params
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

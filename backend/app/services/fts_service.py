"""FTS5 全文检索服务 — 面试题库 RAG 检索（零 embedding 模型依赖）"""
import logging
from app.db.connection import get_db_connection

logger = logging.getLogger("interview-boss")


def sync_fts_entry(question_bank_id: int) -> None:
    """同步单条题目到 FTS5 索引（新增或更新时调用）"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT question, cat1, cat2, tags, ai_answer FROM question_bank WHERE id = ?",
            (question_bank_id,)
        ).fetchone()
        if not row:
            return

        # 先删除旧记录（FTS5 delete 需要用原 rowid）
        conn.execute(
            "DELETE FROM question_fts WHERE rowid = ?",
            (question_bank_id,)
        )
        # 插入新记录
        conn.execute(
            "INSERT INTO question_fts(rowid, question, cat1, cat2, tags, ai_answer) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (question_bank_id, row[0] or '', row[1] or '', row[2] or '', row[3] or '', row[4] or '')
        )
        conn.commit()


def delete_fts_entry(question_bank_id: int) -> None:
    """从 FTS5 索引中删除一条题目"""
    with get_db_connection() as conn:
        conn.execute(
            "DELETE FROM question_fts WHERE rowid = ?",
            (question_bank_id,)
        )
        conn.commit()


def search_questions_fts(keywords: list[str], limit: int = 10) -> list[dict]:
    """用 FTS5 搜索题库，返回最相关的题目列表。

    Args:
        keywords: LLM 提取的关键词列表
        limit: 返回结果数量上限

    Returns:
        [{"id": int, "question": str, "cat1": str, "cat2": str, "tags": str, "rank": float}]
    """
    if not keywords:
        return []

    # 构建 FTS5 查询：OR 连接各关键词
    # 对中文关键词加引号避免分词问题
    terms = []
    for kw in keywords:
        kw = kw.strip()
        if kw:
            # FTS5 通配符搜索，支持部分匹配
            terms.append(f'"{kw}"')
    if not terms:
        return []

    fts_query = " OR ".join(terms)

    with get_db_connection() as conn:
        try:
            rows = conn.execute(
                "SELECT rowid, question, cat1, cat2, tags, ai_answer, rank "
                "FROM question_fts "
                "WHERE question_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ?",
                (fts_query, limit)
            ).fetchall()
        except Exception as e:
            logger.warning(f"FTS5 查询失败: {e}, query={fts_query}")
            # 降级：用 LIKE 查询
            return _fallback_like_search(keywords, conn, limit)

    results = []
    for row in rows:
        results.append({
            "id": row[0],
            "question": row[1],
            "cat1": row[2],
            "cat2": row[3],
            "tags": row[4],
            "ai_answer": row[5],
            "rank": row[6],
        })

    # 如果 FTS 结果太少，用 LIKE 补充
    if len(results) < 3 and keywords:
        existing_ids = {r["id"] for r in results}
        fallback = _fallback_like_search(keywords, conn, limit)
        for item in fallback:
            if item["id"] not in existing_ids:
                results.append(item)
                if len(results) >= limit:
                    break

    return results[:limit]


def _fallback_like_search(keywords: list[str], conn, limit: int) -> list[dict]:
    """降级搜索：当 FTS5 查询失败时用 LIKE 模糊匹配"""
    if not keywords:
        return []

    conditions = []
    params = []
    for kw in keywords[:5]:  # 最多用5个关键词
        kw = kw.strip()
        if kw:
            conditions.append(
                "(question LIKE ? OR cat1 LIKE ? OR cat2 LIKE ? OR tags LIKE ?)"
            )
            pattern = f"%{kw}%"
            params.extend([pattern] * 4)

    if not conditions:
        return []

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT id, question, cat1, cat2, tags, ai_answer "
        f"FROM question_bank "
        f"WHERE deleted_at IS NULL AND status = 'approved' AND ({where}) "
        f"LIMIT ?",
        params + [limit]
    ).fetchall()

    return [
        {
            "id": row[0],
            "question": row[1],
            "cat1": row[2],
            "cat2": row[3],
            "tags": row[4],
            "ai_answer": row[5],
            "rank": 0,
        }
        for row in rows
    ]

"""FTS5 全文检索服务 — 面试题库 RAG 检索（零 embedding 模型依赖）"""
import re
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


def search_questions_fts(keywords: list[str], limit: int = 10, job_position: str = None, exclude_ids: set[int] = None) -> list[dict]:
    """用 FTS5 搜索题库，返回最相关的题目列表。

    Args:
        keywords: LLM 提取的关键词列表
        limit: 返回结果数量上限
        job_position: 目标岗位名，用于过滤题目
        exclude_ids: 已展示的题目 ID 集合，用于去重

    Returns:
        [{"id": int, "question": str, "cat1": str, "cat2": str, "tags": str, "rank": float}]
    """
    if not keywords:
        logger.info("FTS 检索: 无关键词，跳过")
        return []

    logger.info(f"FTS 检索开始: keywords={keywords}, job_position={job_position}")

    # 构建 FTS5 查询：OR 连接各关键词（CJK 文本用 AND 过于严格）
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

    has_cjk = any(re.search(r'[一-鿿]', kw) for kw in keywords)

    rows = []
    with get_db_connection() as conn:
        # 检测 CJK 关键词：unicode61 tokenizer 不支持 CJK，直接用 LIKE 搜索
        if has_cjk:
            logger.info(f"FTS 检索: 检测到 CJK 关键词，跳过 FTS5 直接用 LIKE 搜索")
            results = _fallback_like_search(keywords, conn, limit, job_position, exclude_ids)
            logger.info(f"FTS 检索完成(LIKE): 返回 {len(results)} 条结果")
            return results

        # 英文关键词用 FTS5
        # 优先按岗位过滤搜索
        if job_position:
            try:
                rows = conn.execute(
                    "SELECT f.rowid, f.question, f.cat1, f.cat2, f.tags, f.ai_answer, f.rank "
                    "FROM question_fts f "
                    "JOIN question_bank qb ON f.rowid = qb.id "
                    "WHERE question_fts MATCH ? AND qb.job_position = ? "
                    "AND qb.deleted_at IS NULL AND qb.status = 'approved' "
                    "ORDER BY f.rank LIMIT ?",
                    (fts_query, job_position, limit)
                ).fetchall()
            except Exception as e:
                logger.warning(f"FTS5 岗位过滤查询失败: {e}")

        # 岗位过滤结果不足时，回退到无过滤搜索
        if len(rows) < 3:
            try:
                fallback_rows = conn.execute(
                    "SELECT rowid, question, cat1, cat2, tags, ai_answer, rank "
                    "FROM question_fts "
                    "WHERE question_fts MATCH ? "
                    "ORDER BY rank "
                    "LIMIT ?",
                    (fts_query, limit)
                ).fetchall()
                # 合并去重
                existing_ids = {row[0] for row in rows}
                for row in fallback_rows:
                    if row[0] not in existing_ids:
                        rows.append(row)
                        if len(rows) >= limit:
                            break
            except Exception as e:
                logger.warning(f"FTS5 查询失败: {e}, query={fts_query}")
                if not rows:
                    logger.info("FTS5 查询异常，降级到 LIKE 搜索")
                    results = _fallback_like_search(keywords, conn, limit, job_position, exclude_ids)
                    logger.info(f"FTS 检索完成(LIKE fallback): 返回 {len(results)} 条结果")
                    return results

    # 排除已展示的题目
    if exclude_ids:
        rows = [r for r in rows if r[0] not in exclude_ids]

    results = []
    for row in rows[:limit]:
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
        fallback = _fallback_like_search(keywords, conn, limit, job_position, exclude_ids)
        for item in fallback:
            if item["id"] not in existing_ids:
                results.append(item)
                if len(results) >= limit:
                    break

    logger.info(f"FTS 检索完成(FTS5): 返回 {len(results)} 条结果")
    return results[:limit]


def _fallback_like_search(keywords: list[str], conn, limit: int, job_position: str = None, exclude_ids: set[int] = None) -> list[dict]:
    """降级搜索：当 FTS5 不可用时用 LIKE 模糊匹配

    使用 OR 连接关键词（CJK 查询 AND 过于严格，OR 能召回更多相关题目）。
    长关键词会被拆分为独立的中文词/英文词，提高匹配概率。
    """
    if not keywords:
        return []

    # 拆分长关键词为更小的片段（提高 LIKE 匹配率）
    # 例如 "整体架构分为四层" → ["整体", "架构", "四层"]
    split_keywords = []
    for kw in keywords[:5]:
        kw = kw.strip()
        if not kw:
            continue
        if len(kw) <= 4:
            split_keywords.append(kw)
        else:
            # 按2-3字窗口滑动切分 CJK 文本
            cjk_chars = re.findall(r'[一-鿿]', kw)
            eng_parts = re.findall(r'[a-zA-Z][a-zA-Z0-9]+', kw)
            # CJK: 取2字窗口，跳过停用短语
            stop_parts = {"的", "了", "是", "在", "和", "与", "从", "到", "中", "把", "被", "让", "给", "对", "向", "往", "用", "以", "为"}
            for i in range(len(cjk_chars) - 1):
                chunk = cjk_chars[i] + cjk_chars[i+1]
                if chunk not in stop_parts:
                    split_keywords.append(chunk)
            split_keywords.extend(eng_parts[:3])

    if not split_keywords:
        return []

    # 第一轮：用原始关键词搜索（精确匹配）
    rows = _execute_like_search(split_keywords[:8], conn, limit, job_position)

    # 如果结果不足，用更宽泛的搜索（去掉过长的关键词）
    if len(rows) < 3:
        broad_keywords = [kw for kw in split_keywords if len(kw) <= 6][:8]
        if broad_keywords and broad_keywords != split_keywords[:8]:
            more_rows = _execute_like_search(broad_keywords, conn, limit, job_position)
            existing_ids = {r[0] for r in rows}
            for r in more_rows:
                if r[0] not in existing_ids:
                    rows.append(r)

    if exclude_ids:
        rows = [r for r in rows if r[0] not in exclude_ids]

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
        for row in rows[:limit]
    ]


def _execute_like_search(keywords: list[str], conn, limit: int, job_position: str = None) -> list:
    """执行 LIKE 搜索的核心逻辑"""
    if not keywords:
        return []

    conditions = []
    params = []
    for kw in keywords:
        if kw:
            conditions.append(
                "(question LIKE ? OR cat1 LIKE ? OR cat2 LIKE ? OR tags LIKE ?)"
            )
            pattern = f"%{kw}%"
            params.extend([pattern] * 4)

    if not conditions:
        return []

    position_filter = ""
    if job_position:
        position_filter = "AND job_position = ? "
        params.append(job_position)

    where = " OR ".join(conditions)
    return conn.execute(
        f"SELECT id, question, cat1, cat2, tags, ai_answer "
        f"FROM question_bank "
        f"WHERE deleted_at IS NULL AND status = 'approved' {position_filter}AND ({where}) "
        f"LIMIT ?",
        params + [limit]
    ).fetchall()

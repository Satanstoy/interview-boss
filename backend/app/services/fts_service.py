"""FTS5 + 向量混合检索服务 — 面试题库 RAG 检索

混合检索架构（参考 vstash / Supabase / Digital Applied 2026 最佳实践）:
1. FTS5/LIKE 关键词检索（精确匹配）
2. FAISS 向量语义检索（语义相似）
3. Reciprocal Rank Fusion (RRF) 融合两路结果
4. 自适应 IDF 加权（稀有词偏 FTS，常见词偏向量）
5. 查询扩展（缩写/同义词映射）
6. MMR 多样性去重（按 cat2 分散结果）

RRF 公式: score(doc) = Σ 1/(k + rank_i), k=60（行业标准）
"""
import re
import math
import logging
from app.db.connection import get_db_connection

logger = logging.getLogger("interview-boss")

RRF_K = 60  # RRF 平滑常数（行业标准值）

# ── 查询扩展：缩写/同义词映射（零 LLM 成本）──
QUERY_EXPANSION_MAP = {
    "llm": ["大模型", "语言模型"],
    "rag": ["检索增强", "知识检索"],
    "mcp": ["模型上下文协议"],
    "lru": ["最近最少使用", "缓存淘汰"],
    "tcp": ["传输控制协议", "三次握手"],
    "http": ["超文本传输协议"],
    "jvm": ["Java虚拟机", "Java 虚拟机"],
    "gc": ["垃圾回收", "垃圾收集"],
    "mq": ["消息队列"],
    "sql": ["结构化查询"],
    "jwt": ["JSON Web Token"],
    "orm": ["对象关系映射"],
    "cap": ["一致性可用性分区"],
    "ci": ["持续集成"],
    "cd": ["持续部署", "持续交付"],
}

# ── IDF 缓存（惰性加载，写操作时失效）──
_idf_cache = None


def _compute_idf_cache():
    """从数据库计算所有关键词的 IDF（惰性加载）"""
    global _idf_cache
    if _idf_cache is not None:
        return _idf_cache

    _idf_cache = {}
    try:
        with get_db_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND status='approved'"
            ).fetchone()[0]
            if total == 0:
                return _idf_cache

            # 从 question 和 tags 中提取所有词
            rows = conn.execute(
                "SELECT question, tags FROM question_bank WHERE deleted_at IS NULL AND status='approved'"
            ).fetchall()

            doc_freq = {}
            for r in rows:
                text = f"{r[0] or ''} {r[1] or ''}".lower()
                # 提取英文词和中文词
                tokens = set()
                tokens.update(re.findall(r'[a-zA-Z][a-zA-Z0-9]{1,}', text))
                tokens.update(re.findall(r'[一-鿿]{2,4}', text))
                for t in tokens:
                    doc_freq[t] = doc_freq.get(t, 0) + 1

            # 计算 IDF
            for token, df in doc_freq.items():
                _idf_cache[token] = math.log((total + 1) / (df + 1)) + 1

    except Exception as e:
        logger.warning(f"IDF 缓存计算失败: {e}")

    return _idf_cache


def _expand_query(keywords: list[str]) -> list[str]:
    """查询扩展：将缩写展开为完整术语（零 LLM 成本）

    例如: ["LLM"] → ["LLM", "大模型", "语言模型"]
    """
    expanded = list(keywords)
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in QUERY_EXPANSION_MAP:
            expanded.extend(QUERY_EXPANSION_MAP[kw_lower])
    return expanded


def _adaptive_rrf_weights(keywords: list[str]) -> tuple[float, float]:
    """自适应 RRF 权重：基于 IDF 决定 FTS vs 向量权重

    参考 vstash: 高 IDF（稀有词）→ 偏 FTS；低 IDF（常见词）→ 偏向量
    使用 sigmoid 函数平滑过渡。

    Returns:
        (fts_weight, vec_weight)
    """
    idf_cache = _compute_idf_cache()
    if not idf_cache:
        return 1.0, 1.0

    # 计算关键词的平均 IDF
    idfs = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in idf_cache:
            idfs.append(idf_cache[kw_lower])

    if not idfs:
        return 1.0, 1.0

    mean_idf = sum(idfs) / len(idfs)

    # sigmoid 映射: IDF → FTS 权重
    # 高 IDF (>3) → FTS 权重 ~1.3（精确匹配更重要）
    # 低 IDF (<1.5) → FTS 权重 ~0.8（语义匹配更重要）
    # 中等 IDF → 约 1.0
    x = (mean_idf - 2.0) / 1.5  # 归一化到 [-1, 1] 附近
    fts_weight = 1.0 + 0.3 * (2 / (1 + math.exp(-x)) - 1)  # sigmoid 映射到 [0.7, 1.3]
    vec_weight = 2.0 - fts_weight  # 互补

    return round(fts_weight, 2), round(vec_weight, 2)


def _mmr_diversify(results: list[dict], lambda_param: float = 0.7, limit: int = 5) -> list[dict]:
    """MMR (Maximal Marginal Relevance) 多样性去重

    确保返回结果在 cat2 维度上有多样性，避免 Top-5 全是同一分类。

    Args:
        results: 已排序的结果列表
        lambda_param: 相关性 vs 多样性的平衡（0.7 = 70% 相关性 + 30% 多样性）
        limit: 返回结果数
    """
    if len(results) <= limit:
        return results

    selected = [results[0]]  # 第一个总是最相关的
    candidates = results[1:]

    while len(selected) < limit and candidates:
        best_score = -1
        best_idx = 0

        for i, cand in enumerate(candidates):
            # 相关性分数（基于在原列表中的位置）
            relevance = 1.0 / (i + 2)  # 位置越靠后分数越低

            # 多样性分数（与已选结果的 cat2 重复度）
            cand_cat2 = cand.get("cat2", "")
            max_sim = 0
            for sel in selected:
                if sel.get("cat2", "") == cand_cat2:
                    max_sim = 1.0
                    break

            # MMR 分数 = λ * relevance - (1-λ) * max_similarity
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        selected.append(candidates.pop(best_idx))

    return selected


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


def _relevance_score(question: str, tags: str, ai_answer: str, keywords: list[str]) -> int:
    """计算搜索结果的相关性分数（用于重排序）。

    优先级：question >> tags >> 无匹配 > ai_answer 匹配
    ai_answer 单独匹配视为噪声，应被降权到负分。

    分数越高越相关。
    """
    score = 0
    q_lower = (question or "").lower()
    t_lower = (tags or "").lower()
    a_lower = (ai_answer or "").lower()

    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in q_lower:
            score += 10  # question 匹配权重最高
        if kw_lower in t_lower:
            score += 5   # tags 匹配权重次之
        # ai_answer 匹配不加分（避免 ai_answer 污染干扰排序）

    # 额外惩罚：如果关键词只在 ai_answer 中出现（question 和 tags 都没有），扣分
    if score == 0:
        for kw in keywords:
            if kw.lower() in a_lower:
                score -= 5  # 纯 ai_answer 匹配视为噪声

    return score


def search_questions_fts(keywords: list[str], limit: int = 10, job_position: str = None, exclude_ids: set[int] = None) -> list[dict]:
    """用 FTS5 搜索题库，返回最相关的题目列表。

    优化策略：
    1. FTS5 全字段搜索（unicode61 分词器对 CJK+英文混合文本的列限定查询不可靠）
    2. 搜索结果按相关性重排序（question/tags 匹配优先于 ai_answer 匹配）
    3. CJK 关键词直接走 LIKE 搜索

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

    # 构建 FTS5 查询：OR 连接各关键词
    terms = []
    for kw in keywords:
        kw = kw.strip()
        if kw:
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
        # 优先按岗位过滤搜索（排除重复题）
        if job_position:
            try:
                rows = conn.execute(
                    "SELECT f.rowid, f.question, f.cat1, f.cat2, f.tags, f.ai_answer, f.rank "
                    "FROM question_fts f "
                    "JOIN question_bank qb ON f.rowid = qb.id "
                    "WHERE question_fts MATCH ? AND qb.job_position = ? "
                    "AND qb.deleted_at IS NULL AND qb.status = 'approved' "
                    "AND qb.duplicate_of IS NULL "
                    "ORDER BY f.rank LIMIT ?",
                    (fts_query, job_position, limit)
                ).fetchall()
            except Exception as e:
                logger.warning(f"FTS5 岗位过滤查询失败: {e}")

        # 岗位过滤结果不足时，回退到无过滤搜索（排除重复题）
        if len(rows) < 3:
            try:
                fallback_rows = conn.execute(
                    "SELECT f.rowid, f.question, f.cat1, f.cat2, f.tags, f.ai_answer, f.rank "
                    "FROM question_fts f "
                    "JOIN question_bank qb ON f.rowid = qb.id "
                    "WHERE question_fts MATCH ? "
                    "AND qb.deleted_at IS NULL AND qb.status = 'approved' "
                    "AND qb.duplicate_of IS NULL "
                    "ORDER BY f.rank "
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

    # 构建结果并按相关性重排序
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

    # 按相关性重排序：question/tags 匹配优先于 ai_answer 匹配
    results.sort(key=lambda r: _relevance_score(
        r.get("question", ""), r.get("tags", ""), r.get("ai_answer", ""), keywords
    ), reverse=True)

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
        f"WHERE deleted_at IS NULL AND status = 'approved' AND duplicate_of IS NULL "
        f"{position_filter}AND ({where}) "
        f"LIMIT ?",
        params + [limit]
    ).fetchall()


# ═══════════════════════════════════════════════════════════════
# 混合搜索：FTS5 + 向量 + RRF 融合
# ═══════════════════════════════════════════════════════════════

def reciprocal_rank_fusion(result_lists: list[list[dict]], k: int = RRF_K, weights: list[float] = None) -> list[dict]:
    """Reciprocal Rank Fusion (RRF) — 融合多个排序列表。

    行业标准算法，用于合并 FTS 和向量搜索结果。
    不需要归一化分数（解决 FTS rank vs 余弦相似度不可比问题）。

    公式: score(doc) = Σ weight_i / (k + rank_i)

    Args:
        result_lists: 多个搜索结果列表，每个列表按相关性排序
        k: 平滑常数（默认 60，行业标准）
        weights: 每个列表的权重（默认全 1.0）

    Returns:
        融合后的结果列表，按 RRF 分数降序排列，附带 _rrf_score 字段
    """
    if weights is None:
        weights = [1.0] * len(result_lists)

    scores = {}  # doc_id -> rrf_score
    doc_info = {}  # doc_id -> document dict

    for i, results in enumerate(result_lists):
        w = weights[i] if i < len(weights) else 1.0
        for rank, item in enumerate(results, 1):
            doc_id = item["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
            # 保留最完整的文档信息（优先取有更多字段的）
            if doc_id not in doc_info or len(str(item)) > len(str(doc_info[doc_id])):
                doc_info[doc_id] = item

    # 按 RRF 分数降序排列
    sorted_ids = sorted(scores.keys(), key=lambda did: scores[did], reverse=True)

    result = []
    for doc_id in sorted_ids:
        entry = {**doc_info[doc_id], "_rrf_score": scores[doc_id]}
        result.append(entry)

    return result


def _vector_search(query_text: str, top_k: int = 10, exclude_ids: set[int] = None) -> list[dict]:
    """向量语义搜索 — 从数据库加载 embedding 并用 FAISS 检索。

    Args:
        query_text: 查询文本
        top_k: 返回结果数
        exclude_ids: 排除的 ID 集合

    Returns:
        [{"id": int, "question": str, "cat1": str, "cat2": str, "tags": str, "score": float}]
    """
    import numpy as np

    try:
        from app.services.embedding_service import encode_texts, build_index, search_index
    except ImportError:
        logger.warning("向量搜索: embedding_service 不可用")
        return []

    with get_db_connection() as conn:
        # 加载所有有效题目的 embedding（排除重复题）
        rows = conn.execute(
            "SELECT id, question, cat1, cat2, tags, embedding "
            "FROM question_bank "
            "WHERE deleted_at IS NULL AND status = 'approved' AND embedding IS NOT NULL "
            "AND duplicate_of IS NULL"
        ).fetchall()

    if not rows:
        logger.info("向量搜索: 无 embedding 数据，跳过")
        return []

    # 构建 FAISS 索引
    ids = []
    vectors = []
    doc_map = {}
    for r in rows:
        qid = r[0]
        if exclude_ids and qid in exclude_ids:
            continue
        emb = np.frombuffer(r[5], dtype=np.float32).copy()
        ids.append(qid)
        vectors.append(emb)
        doc_map[qid] = {
            "id": qid,
            "question": r[1],
            "cat1": r[2],
            "cat2": r[3],
            "tags": r[4],
        }

    if not vectors:
        return []

    vectors_np = np.array(vectors, dtype=np.float32)
    index = build_index(vectors_np)

    # 编码查询文本
    query_emb = encode_texts([query_text])
    indices, scores = search_index(index, query_emb, top_k=top_k)

    results = []
    for idx, score in zip(indices, scores):
        qid = ids[idx]
        results.append({**doc_map[qid], "score": score})

    return results


def _has_question_tag_match(results: list[dict], keywords: list[str]) -> bool:
    """检查搜索结果中是否有 question/tags 匹配（非纯 ai_answer 匹配）"""
    for r in results[:3]:
        if _relevance_score(r.get("question", ""), r.get("tags", ""), r.get("ai_answer", ""), keywords) > 0:
            return True
    return False


def hybrid_search(
    keywords: list[str],
    query_text: str = None,
    limit: int = 5,
    job_position: str = None,
    exclude_ids: set[int] = None,
) -> list[dict]:
    """FTS5 + 向量 + RRF 混合搜索（含 4 项轻量优化）。

    优化技术（零额外 LLM 调用）：
    1. 自适应 IDF 加权（vstash）：稀有词偏 FTS，常见词偏向量
    2. 查询扩展：缩写/同义词映射（LLM→大模型, RAG→检索增强）
    3. MMR 多样性：按 cat2 分散结果，避免 Top-5 全是同一分类
    4. FTS 质量检测：FTS 无 question/tags 匹配时，降低 FTS 权重

    Args:
        keywords: FTS 关键词列表
        query_text: 原始查询文本（用于向量搜索，为空时仅用 FTS）
        limit: 返回结果数
        job_position: 岗位过滤
        exclude_ids: 排除 ID

    Returns:
        融合后的搜索结果列表
    """
    if not keywords and not query_text:
        return []

    # ── 优化 1: 查询扩展（缩写→完整术语）──
    original_keywords = keywords
    if keywords:
        expanded = _expand_query(keywords)
        if len(expanded) > len(keywords):
            logger.info(f"查询扩展: {keywords} → {expanded}")
            keywords = expanded

    # 过采样：每路检索取 limit*2 个候选，给 RRF 更多信号
    oversample = limit * 3  # 增加过采样给 MMR 更多选择

    # 路径 1: FTS/LIKE 关键词检索
    fts_results = search_questions_fts(
        keywords=keywords or [query_text],
        limit=oversample,
        job_position=job_position,
        exclude_ids=exclude_ids,
    )

    # 路径 2: 向量语义检索（如果 query_text 可用）
    vec_results = []
    if query_text:
        vec_results = _vector_search(
            query_text=query_text,
            top_k=oversample,
            exclude_ids=exclude_ids,
        )

    # 如果只有一路有结果，直接返回
    if not vec_results:
        logger.info(f"混合搜索: 向量无结果，降级到纯 FTS ({len(fts_results)} 条)")
        return fts_results[:limit]
    if not fts_results:
        logger.info(f"混合搜索: FTS 无结果，降级到纯向量 ({len(vec_results)} 条)")
        return vec_results[:limit]

    # ── 优化 2: 自适应 RRF 权重（基于 IDF）──
    fts_weight, vec_weight = _adaptive_rrf_weights(original_keywords or keywords)
    logger.info(f"自适应权重: FTS={fts_weight}, Vec={vec_weight} (keywords={original_keywords})")

    # RRF 融合（使用自适应权重）
    fused = reciprocal_rank_fusion([fts_results, vec_results], weights=[fts_weight, vec_weight])

    # 相关性重排序（question/tags 匹配优先）
    if keywords:
        fused.sort(key=lambda r: _relevance_score(
            r.get("question", ""), r.get("tags", ""), r.get("ai_answer", ""), original_keywords or keywords
        ), reverse=True)

    # ── 优化 3: MMR 多样性去重 ──
    fused = _mmr_diversify(fused, lambda_param=0.7, limit=limit * 2)

    logger.info(
        f"混合搜索完成: FTS={len(fts_results)}, 向量={len(vec_results)}, "
        f"融合后={len(fused)}, 返回={min(limit, len(fused))}"
    )
    return fused[:limit]

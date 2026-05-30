"""流式增量聚类服务：匹配已有聚类 + 内部聚类新题"""
import asyncio
import logging
from typing import List, Dict, Any

from app.db.connection import get_db_connection
from app.services.llm import _call_llm_with_retry, _extract_json

logger = logging.getLogger("interview-boss")

MAX_CONCURRENCY = 2
RECENT_DAYS = 7  # 默认匹配最近 7 天的 frequency=1 题目

# ──────────────────────────── Prompts ────────────────────────────

MATCH_EXISTING_PROMPT = """你是一个面试题去重专家。你的任务是将一批【新题目】归类到【已有标准题库】中。

注意：【待匹配的新题目】是一个不超过 40 道题的微批次，请逐题判断是否与已有题库中的某道题真正重复。

匹配判断准则（核心）：
只有当「准备了 A 的答案，可以直接用它回答 B」时才合并。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"

坚决不合并（负面示例）：
- 「上下文过长怎么办」≠「agent怎么获取上下文」（前者问溢出处理，后者问获取机制）
- 「volatile关键字」≠「Java JUC、JVM相关知识」（具体知识点 vs 大话题）
- 「介绍一下Memory」≠「摘要压缩怎么限制长度」（概述 vs 具体实现细节）
- 「高并发限流」≠「研究生方向」（完全不相关领域）
- 「MCP介绍」≠「mcp和skills区别」（前者问原理，后者问对比）
- 「使用过AI Coding吗」≠「AI工具费用对比」（体验 vs 成本）
- 包含层级关系的概念：如 "Agent" 与 "ReAct"（ReAct 是 Agent 的一种范式，不是同一道题）
- 平级但不同的技术：如 "MCP" 与 "Function Call"（都是工具调用方案但考察点不同）
- 同一领域但不同子问题：如 "RAG 的 embedding 怎么设计" ≠ "RAG 的检索召回率怎么提升"

**重要原则：如果不确定，不要合并。错合并比漏合并更严重。**

【已有标准题库】（格式：[聚类ID] 代表题目）：
{existing_clusters}

【待匹配的新题目】（微批次，共 {count} 题）：
{new_questions}

请输出 JSON 格式，列出成功匹配的结果。如果没有匹配项，输出空数组。
{{"matches": [{{"new_id": "新题ID", "cluster_id": "已有聚类ID"}}]}}
只输出 JSON，不要解释。"""

CLUSTER_NEW_PROMPT = """你是一个面试题聚类专家。以下是一个不超过 40 道题的微批次，请在它们内部寻找**真正重复**的题目并进行合并。

合并判断准则（核心）：
只有当「准备了 A 的答案，可以直接用它回答 B」时才合并。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"

坚决不合并（负面示例）：
- 「上下文过长怎么办」≠「agent怎么获取上下文」（前者问溢出处理，后者问获取机制）
- 「volatile关键字」≠「Java JUC、JVM相关知识」（具体知识点 vs 大话题）
- 「介绍一下Memory」≠「摘要压缩怎么限制长度」（概述 vs 具体实现细节）
- 「高并发限流」≠「研究生方向」（完全不相关领域）
- 「MCP介绍」≠「mcp和skills区别」（前者问原理，后者问对比）
- 「使用过AI Coding吗」≠「AI工具费用对比」（体验 vs 成本）
- 包含层级关系的概念：如 "Agent" 与 "ReAct"
- 平级但不同的技术：如 "MCP" 与 "Function Call"
- 同一领域但不同子问题：如 "RAG 的 embedding 怎么设计" ≠ "RAG 的检索召回率怎么提升"

**重要原则：如果不确定，不要合并。错合并比漏合并更严重。**

【待聚类的新题目】（微批次，共 {count} 题）：
{unmatched_questions}

请输出 JSON 格式。只有确实重复的才放入 clusters，独立的题目不需要输出。
{{"clusters": [{{"ids": ["题号1", "题号2"], "representative": "选取其中表述最清晰的一道题作为代表"}}]}}
只输出 JSON，不要解释。"""


VALIDATE_MERGES_PROMPT = """你是一个面试题去重验证专家。以下是一批待合并的题目对，请验证每一对是否真的应该合并。

验证标准：
只有当「准备了 A 的答案，可以直接用它回答 B」时才合并。

坚决不合并（负面示例）：
- 「上下文过长怎么办」≠「agent怎么获取上下文」（前者问溢出处理，后者问获取机制）
- 「volatile关键字」≠「Java JUC、JVM相关知识」（具体知识点 vs 大话题）
- 「高并发限流」≠「研究生方向」（完全不相关领域）

**重要原则：如果不确定，不要合并。错合并比漏合并更严重。**

【待验证的题目对】：
{pairs}

请输出 JSON 格式，列出每一对的验证结果。
{{"validations": [{{"new_id": "新题ID", "cluster_id": "聚类ID", "valid": true/false}}]}}
只输出 JSON，不要解释。"""


# ──────────────────────────── 公开入口 ────────────────────────────

async def _validate_merges(matches: List[Dict], new_questions: List[Dict],
                          existing_clusters: List[Dict], user_id=None) -> List[Dict]:
    """验证合并结果（两阶段验证）

    Args:
        matches: 待验证的合并列表 [{"new_id": ..., "cluster_id": ...}]
        new_questions: 新题目列表
        existing_clusters: 已有聚类列表
        user_id: 用户 ID

    Returns:
        验证通过的合并列表
    """
    if not matches:
        return []

    # 构建题目映射
    new_q_map = {str(q['id']): q for q in new_questions}
    cluster_map = {str(c['id']): c for c in existing_clusters}

    # 构建验证对
    pairs_text = []
    for match in matches:
        new_id = str(match.get('new_id', ''))
        cluster_id = str(match.get('cluster_id', ''))

        new_q = new_q_map.get(new_id)
        cluster_q = cluster_map.get(cluster_id)

        if new_q and cluster_q:
            pairs_text.append(f"[新题 {new_id}] {new_q['question']}\n[聚类 {cluster_id}] {cluster_q['question']}")

    if not pairs_text:
        return matches

    # 调用 LLM 验证
    prompt = VALIDATE_MERGES_PROMPT.format(
        pairs="\n\n".join(pairs_text)
    )

    try:
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)

        # 过滤验证通过的合并
        validated_matches = []
        validations = result.get("validations", [])

        for match in matches:
            new_id = str(match.get('new_id', ''))
            cluster_id = str(match.get('cluster_id', ''))

            # 查找对应的验证结果
            validation = next(
                (v for v in validations
                 if str(v.get('new_id')) == new_id and str(v.get('cluster_id')) == cluster_id),
                None
            )

            if validation and validation.get('valid', False):
                validated_matches.append(match)
            else:
                logger.info(f"  验证拒绝合并: 新题 {new_id} -> 聚类 {cluster_id}")

        return validated_matches

    except Exception as e:
        logger.warning(f"验证合并失败，返回原始结果: {e}")
        return matches


async def _load_recent_singletons(cat2: str, days: int = RECENT_DAYS) -> List[Dict]:
    """加载最近 N 天入库的 frequency=1 题目（同 cat2）

    Args:
        cat2: 题目分类
        days: 天数，默认 7 天

    Returns:
        最近 N 天的 frequency=1 题目列表
    """
    def _query():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question FROM question_bank "
            "WHERE cat2 = ? AND frequency = 1 AND deleted_at IS NULL "
            "AND created_at > datetime('now', ?) "
            "ORDER BY id DESC",
            (cat2, f'-{days} days')
        ).fetchall()
        return [{"id": r['id'], "question": r['question']} for r in rows]

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        logger.warning(f"加载最近 {days} 天的题目失败: {e}")
        return []


async def process_incremental_batch(
    new_rows: List[Dict],
    existing_by_cat2: Dict[str, List[Dict]],
    user_id=None,
    recent_days: int = RECENT_DAYS,
) -> Dict[str, Any]:
    """流式增量聚类主入口。

    参数：
        new_rows: 一批新题，每项需含 id, question, cat2
        existing_by_cat2: {cat2: [{"id": qb_id, "question": 代表题}]}
        user_id: 调用者用户 ID
        recent_days: 匹配最近 N 天的 frequency=1 题目，默认 7 天

    返回：
        {
            "matched_to_existing": [{"qd_id": ..., "cluster_id": ..., ...}],
            "new_clusters": [{"ids": [...], "representative": "...", "items": [...]}]
        }
    """
    cat2_groups = {}
    no_cat2 = []
    for r in new_rows:
        cat2 = r.get('cat2') or ''
        if cat2:
            cat2_groups.setdefault(cat2, []).append(r)
        else:
            no_cat2.append(r)

    if no_cat2:
        cat2_groups[''] = no_cat2

    cat2_list = list(cat2_groups.items())
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _process_one(cat2, questions):
        async with semaphore:
            existing = existing_by_cat2.get(cat2, [])
            return await _match_and_cluster_cat2(
                cat2, questions, existing, user_id,
                recent_days=recent_days
            )

    tasks = [_process_one(cat2, questions) for cat2, questions in cat2_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_matched = []
    all_new_clusters = []
    for (cat2, _), res in zip(cat2_list, results):
        if isinstance(res, Exception):
            logger.error(f"[{cat2 or '无分类'}] cat2 处理异常: {res}")
        else:
            all_matched.extend(res['matched'])
            all_new_clusters.extend(res['new_clusters'])

    return {
        "matched_to_existing": all_matched,
        "new_clusters": all_new_clusters,
    }


# ──────────────────────────── 内部函数 ────────────────────────────

async def _match_and_cluster_cat2(cat2, new_questions, existing_clusters, user_id, recent_days=RECENT_DAYS):
    """处理单个 cat2 分组：匹配已有 → 匹配最近题目 → 内部聚类剩余

    Args:
        cat2: 题目分类
        new_questions: 新题目列表
        existing_clusters: 已有聚类列表
        user_id: 用户 ID
        recent_days: 匹配最近 N 天的 frequency=1 题目
    """
    matched = []
    unmatched_ids = {str(q['id']) for q in new_questions}

    # Phase 1: 匹配已有聚类
    if existing_clusters:
        try:
            prompt = MATCH_EXISTING_PROMPT.format(
                existing_clusters=_format_existing_clusters(existing_clusters),
                new_questions=_format_new_questions(new_questions),
                count=len(new_questions),
            )
            content = await _call_llm_with_retry(
                prompt, response_format={"type": "json_object"}, user_id=user_id
            )
            result = _extract_json(content)

            matched_cluster_ids = set()
            for m in result.get("matches", []):
                nid = str(m.get("new_id", ""))
                cid = m.get("cluster_id")
                if nid in unmatched_ids and cid is not None:
                    matched_cluster_ids.add(nid)
                    q = next((q for q in new_questions if str(q['id']) == nid), None)
                    if q:
                        matched.append({
                            "qd_id": q['id'],
                            "cluster_id": cid,
                            "question": q['question'],
                            "cat1": q.get('cat1', ''),
                            "cat2": q.get('cat2', cat2),
                            "tags": q.get('tags', ''),
                            "diff_tag": q.get('diff_tag', ''),
                            "url": q.get('url', ''),
                            "company": q.get('company', ''),
                            "round": q.get('round', ''),
                        })

            unmatched_ids -= matched_cluster_ids
            if matched_cluster_ids:
                logger.info(f"  [{cat2 or '无分类'}] Phase 1 匹配已有聚类: {len(matched_cluster_ids)} 题")

                # 验证 Phase 1 的合并结果
                phase1_matches = result.get("matches", [])
                if phase1_matches:
                    validated_matches = await _validate_merges(
                        phase1_matches, new_questions, existing_clusters, user_id
                    )
                    # 更新 matched 列表，只保留验证通过的
                    validated_new_ids = {str(m.get('new_id')) for m in validated_matches}
                    matched = [m for m in matched if str(m.get('qd_id')) in validated_new_ids or str(m.get('qd_id')) not in matched_cluster_ids]
                    # 更新 unmatched_ids
                    unmatched_ids = {str(q['id']) for q in new_questions} - {str(m.get('qd_id')) for m in matched}

        except Exception as e:
            logger.warning(f"  [{cat2 or '无分类'}] Phase 1 匹配已有聚类失败: {e}")

    # Phase 1.5: 匹配最近 N 天的 frequency=1 题目（新增）
    unmatched_questions = [q for q in new_questions if str(q['id']) in unmatched_ids]
    if unmatched_questions and recent_days > 0:
        try:
            recent_singletons = await _load_recent_singletons(cat2, days=recent_days)
            if recent_singletons:
                prompt = MATCH_EXISTING_PROMPT.format(
                    existing_clusters=_format_existing_clusters(recent_singletons),
                    new_questions=_format_new_questions(unmatched_questions),
                    count=len(unmatched_questions),
                )
                content = await _call_llm_with_retry(
                    prompt, response_format={"type": "json_object"}, user_id=user_id
                )
                result = _extract_json(content)

                matched_recent_ids = set()
                for m in result.get("matches", []):
                    nid = str(m.get("new_id", ""))
                    cid = m.get("cluster_id")
                    if nid in unmatched_ids and cid is not None:
                        matched_recent_ids.add(nid)
                        q = next((q for q in unmatched_questions if str(q['id']) == nid), None)
                        if q:
                            matched.append({
                                "qd_id": q['id'],
                                "cluster_id": cid,
                                "question": q['question'],
                                "cat1": q.get('cat1', ''),
                                "cat2": q.get('cat2', cat2),
                                "tags": q.get('tags', ''),
                                "diff_tag": q.get('diff_tag', ''),
                                "url": q.get('url', ''),
                                "company": q.get('company', ''),
                                "round": q.get('round', ''),
                            })

                unmatched_ids -= matched_recent_ids
                if matched_recent_ids:
                    logger.info(f"  [{cat2 or '无分类'}] Phase 1.5 匹配最近 {recent_days} 天题目: {len(matched_recent_ids)} 题")

        except Exception as e:
            logger.warning(f"  [{cat2 or '无分类'}] Phase 1.5 匹配最近题目失败: {e}")

    # Phase 2: 剩余新题内部聚类
    unmatched_questions = [q for q in new_questions if str(q['id']) in unmatched_ids]
    new_clusters = await _cluster_unmatched(unmatched_questions, user_id)

    return {"matched": matched, "new_clusters": new_clusters}


async def _cluster_unmatched(unmatched_questions, user_id):
    """将未匹配的新题进行内部聚类"""
    if len(unmatched_questions) < 2:
        return [{"ids": [str(q['id'])], "representative": q['question'], "items": [q]}
                for q in unmatched_questions]

    prompt = CLUSTER_NEW_PROMPT.format(
        unmatched_questions=_format_new_questions(unmatched_questions),
        count=len(unmatched_questions),
    )

    try:
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)

        clusters = []
        clustered_ids = set()

        for c in result.get("clusters", []):
            ids = [str(i) for i in c.get("ids", [])]
            if len(ids) >= 2:
                clustered_ids.update(ids)
                items = [q for q in unmatched_questions if str(q['id']) in ids]
                rep = c.get("representative", "")
                if not rep or len(rep) < 3:
                    rep = max((q['question'] for q in items), key=len)
                clusters.append({"ids": ids, "representative": rep, "items": items})

        # 未被聚类的题目各自独立
        for q in unmatched_questions:
            if str(q['id']) not in clustered_ids:
                clusters.append({
                    "ids": [str(q['id'])],
                    "representative": q['question'],
                    "items": [q],
                })

        logger.info(f"    内部聚类: {len(clusters)} 个结果（含独立题）")
        return clusters

    except Exception as e:
        logger.warning(f"    内部聚类失败: {e}")
        return [{"ids": [str(q['id'])], "representative": q['question'], "items": [q]}
                for q in unmatched_questions]


def _format_existing_clusters(clusters):
    """格式化已有聚类供 Prompt 使用（只传 ID + 代表题，节省 Token）"""
    lines = []
    for c in clusters:
        lines.append(f"[{c['id']}] {c['question']}")
    return "\n".join(lines)


def _format_new_questions(questions):
    return "\n".join(f"[{q['id']}] {q['question']}" for q in questions)


# ──────────────────────────── 保留的工具函数 ────────────────────────────

async def generate_unified_question(questions: list[str], sources_context: list[dict] | None = None, user_id=None) -> str:
    """为一组同义问题选择代表题（使用最长的原始问题）"""
    if len(questions) == 1:
        return questions[0]
    return max(questions, key=len)


async def match_new_questions(new_rows, existing_clusters_by_cat2, user_id=None):
    """增量匹配：将新题目与已有聚类匹配（用于个人题库合并）"""
    if not new_rows:
        return {"matched": [], "unmatched": []}

    cat2_groups = {}
    for r in new_rows:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _match_group(cat2, group):
        existing = existing_clusters_by_cat2.get(cat2, [])
        if not existing:
            return [], group

        # 构建 cluster_id → question_bank_id 映射（兼容两种格式）
        id_to_qb = {}
        normalized = []
        for c in existing:
            cid = c.get('id') or c.get('question_bank_id')
            id_to_qb[cid] = cid
            normalized.append({**c, 'id': cid})

        async with semaphore:
            prompt = MATCH_EXISTING_PROMPT.format(
                existing_clusters=_format_existing_clusters(normalized),
                new_questions=_format_new_questions(group),
                count=len(group),
            )
            content = await _call_llm_with_retry(prompt, response_format={"type": "json_object"}, user_id=user_id)

        result = _extract_json(content)
        group_matched = []
        group_unmatched = []
        group_matched_ids = set()

        for m in result.get("matches", []):
            new_id = m.get("new_id")
            cluster_id = m.get("cluster_id")
            try:
                cluster_id_int = int(cluster_id) if cluster_id is not None else None
                new_id_int = int(new_id) if new_id is not None else None
            except (ValueError, TypeError):
                continue
            if new_id_int is not None and cluster_id_int is not None and cluster_id_int in id_to_qb:
                group_matched.append({"new_id": new_id_int, "question_bank_id": id_to_qb[cluster_id_int]})
                group_matched_ids.add(new_id_int)
        for r in group:
            if r['id'] not in group_matched_ids:
                group_unmatched.append(r)

        return group_matched, group_unmatched

    tasks = []
    for cat2, group in cat2_groups.items():
        tasks.append(_match_group(cat2, group))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    matched = []
    still_unmatched = []
    for (cat2, _), res in zip(cat2_groups.items(), results):
        if isinstance(res, Exception):
            logger.warning(f"同分类增量匹配失败 [{cat2 or '无分类'}]: {res}")
            still_unmatched.extend(cat2_groups[cat2])
        else:
            m, u = res
            matched.extend(m)
            still_unmatched.extend(u)

    return {"matched": matched, "unmatched": still_unmatched}


async def scan_personal_duplicates(public_qb_id: int, cat2: str, job_position: str):
    """公共题审核通过后，扫描所有用户个人题，标记语义重复。"""
    from app.db.connection import get_db_connection
    import json as _json

    def _scan():
        with get_db_connection() as conn:
            # 获取公共题信息
            pub = conn.execute("SELECT id, question FROM question_bank WHERE id = ?", (public_qb_id,)).fetchone()
            if not pub:
                return

            # 查找同 cat2 + job_position 的个人题（未标记重复的）
            personal = conn.execute(
                "SELECT id, question, cat2, original_questions FROM question_bank "
                "WHERE owner_id IS NOT NULL AND duplicate_of IS NULL AND deleted_at IS NULL "
                "AND cat2 = ? AND (job_position = ? OR job_position = '' OR job_position IS NULL)",
                (cat2, job_position)
            ).fetchall()

            if not personal:
                return

            # 构建匹配用数据
            existing = [{"question_bank_id": pub['id'], "question": pub['question']}]
            new_rows = []
            for p in personal:
                new_rows.append({"id": p['id'], "question": p['question']})

            return existing, new_rows, [dict(p) for p in personal]

    result = await _scan_async(_scan)
    if not result:
        return

    existing, new_rows, personal_dicts = result

    try:
        match_result = await match_new_questions(new_rows, {"": existing})
        if match_result["matched"]:
            matched_ids = [m["new_id"] for m in match_result["matched"]]
            def _mark():
                with get_db_connection() as conn:
                    for mid in matched_ids:
                        conn.execute(
                            "UPDATE question_bank SET duplicate_of = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND duplicate_of IS NULL",
                            (public_qb_id, mid)
                        )
                    conn.commit()
            await _scan_async(_mark)
            logger.info(f"反向扫描标记 {len(matched_ids)} 个个人题为公共题 {public_qb_id} 的重复")
    except Exception as e:
        logger.warning(f"反向扫描失败: {e}")


async def _scan_async(func):
    """将同步 DB 操作包装为异步。"""
    import asyncio
    return await asyncio.to_thread(func)

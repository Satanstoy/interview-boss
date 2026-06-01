"""流式增量聚类服务：匹配已有聚类 + 内部聚类新题"""
import asyncio
import json as _json_mod
import logging
from typing import List, Dict, Any

from app.db.connection import get_db_connection
from app.services.llm import _call_llm_with_retry, _extract_json
from app.services.embedding_service import prefilter_centroids

logger = logging.getLogger("interview-boss")

MAX_CONCURRENCY = 2
RECENT_DAYS = 7  # 默认匹配最近 7 天的 frequency=1 题目
VALIDATION_CONFIDENCE_THRESHOLD = 0.8  # 验证置信度阈值
_PREFILTER_TOP_K = 30  # Embedding 预筛选保留的候选 centroid 数量

# ──────────────────────────── Prompts ────────────────────────────

MATCH_EXISTING_PROMPT = """你是一个面试题去重专家。你的任务是将一批【新题目】归类到【已有标准题库】中。

注意：【待匹配的新题目】是一个不超过 40 道题的微批次，请逐题判断是否与已有题库中的某道题真正重复。

匹配判断准则（核心）：
如果两道题考察的核心知识点相同，只是提问角度不同，就应该合并。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"
- "volatile关键字的作用" ≈ "Java JUC、JVM相关知识"（volatile 属于 JUC 范畴）
- "上下文过长怎么办" ≈ "agent怎么获取上下文"（都涉及上下文管理）
- "MCP介绍" ≈ "mcp和skills区别"（都涉及 MCP 概念）

坚决不合并（负面示例 — 相似但不同知识点）：
- 「Redis 缓存穿透」≠「Redis 缓存雪崩」（同属缓存问题，但穿透是查询不存在的key，雪崩是大面积key同时过期）
- 「MySQL 索引优化」≠「MySQL 查询优化」（索引优化是查询优化的子集，但查询优化还包括执行计划、SQL重写等）
- 「Vue 生命周期」≠「Vue 组件通信」（同一框架不同主题，生命周期钩子 vs props/emit/provide-inject）
- 「TCP 三次握手」≠「TCP 四次挥手」（建立连接 vs 断开连接，流程和状态机完全不同）
- 「JVM 垃圾回收」≠「JVM 内存模型」（GC 算法收集 vs 内存区域划分、可见性规则）
- 「高并发限流」≠「研究生方向」（完全不相关领域）

**重要原则：真正重复的题目应该合并，不要遗漏。只有完全不相关的题才不合并。**

【已有标准题库】（格式：[聚类ID] 代表题目）：
{existing_clusters}

【待匹配的新题目】（微批次，共 {count} 题）：
{new_questions}

请输出 JSON 格式，列出成功匹配的结果。如果没有匹配项，输出空数组。
{{"matches": [{{"new_id": "新题ID", "cluster_id": "已有聚类ID"}}]}}
只输出 JSON，不要解释。"""

CLUSTER_NEW_PROMPT = """你是一个面试题聚类专家。以下是一个不超过 40 道题的微批次，请在它们内部寻找**真正重复**的题目并进行合并。

合并判断准则（核心）：
如果两道题考察的核心知识点相同，只是提问角度不同，就应该合并。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"
- "volatile关键字的作用" ≈ "Java JUC、JVM相关知识"（volatile 属于 JUC 范畴）
- "上下文过长怎么办" ≈ "agent怎么获取上下文"（都涉及上下文管理）
- "MCP介绍" ≈ "mcp和skills区别"（都涉及 MCP 概念）

坚决不合并（负面示例 — 相似但不同知识点）：
- 「Redis 缓存穿透」≠「Redis 缓存雪崩」（同属缓存问题，但穿透是查询不存在的key，雪崩是大面积key同时过期）
- 「MySQL 索引优化」≠「MySQL 查询优化」（索引优化是查询优化的子集，但查询优化还包括执行计划、SQL重写等）
- 「Vue 生命周期」≠「Vue 组件通信」（同一框架不同主题，生命周期钩子 vs props/emit/provide-inject）
- 「TCP 三次握手」≠「TCP 四次挥手」（建立连接 vs 断开连接，流程和状态机完全不同）
- 「JVM 垃圾回收」≠「JVM 内存模型」（GC 算法收集 vs 内存区域划分、可见性规则）
- 「高并发限流」≠「研究生方向」（完全不相关领域）

**重要原则：真正重复的题目应该合并，不要遗漏。只有完全不相关的题才不合并。**

【待聚类的新题目】（微批次，共 {count} 题）：
{unmatched_questions}

请输出 JSON 格式。只有确实重复的才放入 clusters，独立的题目不需要输出。
{{"clusters": [{{"ids": ["题号1", "题号2"], "representative": "选取其中表述最清晰的一道题作为代表"}}]}}
只输出 JSON，不要解释。"""


VALIDATE_MERGES_PROMPT = """你是一个面试题去重验证专家。以下是一批待合并的题目对，请验证每一对是否真的应该合并。

验证标准：
如果两道题考察的核心知识点相同，只是提问角度不同，就应该合并。

可以合并（同一技术点的不同提问角度）：
- "volatile关键字的作用" ≈ "Java JUC、JVM相关知识"（volatile 属于 JUC 范畴）
- "上下文过长怎么办" ≈ "agent怎么获取上下文"（都涉及上下文管理）
- "MCP介绍" ≈ "mcp和skills区别"（都涉及 MCP 概念）

坚决不合并（负面示例 — 相似但不同知识点）：
- 「Redis 缓存穿透」≠「Redis 缓存雪崩」（同属缓存问题，但穿透是查询不存在的key，雪崩是大面积key同时过期）
- 「MySQL 索引优化」≠「MySQL 查询优化」（索引优化是查询优化的子集，但查询优化还包括执行计划、SQL重写等）
- 「Vue 生命周期」≠「Vue 组件通信」（同一框架不同主题，生命周期钩子 vs props/emit/provide-inject）
- 「TCP 三次握手」≠「TCP 四次挥手」（建立连接 vs 断开连接，流程和状态机完全不同）
- 「JVM 垃圾回收」≠「JVM 内存模型」（GC 算法收集 vs 内存区域划分、可见性规则）
- 「高并发限流」≠「研究生方向」（完全不相关领域）

**重要原则：真正重复的题目应该合并，不要遗漏。只有完全不相关的题才不合并。**

【待验证的题目对】：
{pairs}

请输出 JSON 格式，列出每一对的验证结果。confidence 为 0~1 之间的小数，表示你对该合并判断的确信程度。
{{"validations": [{{"new_id": "新题ID", "cluster_id": "聚类ID", "valid": true/false, "confidence": 0.95, "reason": "判断理由（简短）"}}]}}
只输出 JSON，不要解释。"""


# ──────────────────────────── 公开入口 ────────────────────────────

async def _validate_merges(matches: List[Dict], new_questions: List[Dict],
                          existing_clusters: List[Dict], user_id=None):
    """验证合并结果（两阶段验证）

    Args:
        matches: 待验证的合并列表 [{"new_id": ..., "cluster_id": ...}]
        new_questions: 新题目列表
        existing_clusters: 已有聚类列表
        user_id: 用户 ID

    Returns:
        (验证通过的合并列表, 置信度映射 {(new_id, cluster_id): confidence})
    """
    empty_result = ([], {})
    if not matches:
        return empty_result

    # 构建题目映射
    new_q_map = {str(q['id']): q for q in new_questions}
    cluster_map = {str(c['id']): c for c in existing_clusters}

    # 构建验证对
    pairs_text = []
    pair_lookup = {}
    for match in matches:
        new_id = str(match.get('new_id', ''))
        cluster_id = str(match.get('cluster_id', ''))

        new_q = new_q_map.get(new_id)
        cluster_q = cluster_map.get(cluster_id)

        if new_q and cluster_q:
            pairs_text.append(f"[新题 {new_id}] {new_q['question']}\n[聚类 {cluster_id}] {cluster_q['question']}")
            pair_lookup[(new_id, cluster_id)] = (new_q, cluster_q)

    if not pairs_text:
        return (matches, {})

    # 调用 LLM 验证
    prompt = VALIDATE_MERGES_PROMPT.format(
        pairs="\n\n".join(pairs_text)
    )

    try:
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)

        # 过滤验证通过的合并（带置信度阈值）
        validated_matches = []
        confidence_map = {}
        validations = result.get("validations", [])
        rejected_for_review = []

        for match in matches:
            new_id = str(match.get('new_id', ''))
            cluster_id = str(match.get('cluster_id', ''))

            # 查找对应的验证结果
            validation = next(
                (v for v in validations
                 if str(v.get('new_id')) == new_id and str(v.get('cluster_id')) == cluster_id),
                None
            )

            if validation:
                is_valid = validation.get('valid', False)
                confidence = float(validation.get('confidence', 0))
                reason = validation.get('reason', '')
                confidence_map[(new_id, cluster_id)] = confidence

                if is_valid and confidence >= VALIDATION_CONFIDENCE_THRESHOLD:
                    validated_matches.append(match)
                    logger.info(f"  验证通过: 新题 {new_id} -> 聚类 {cluster_id} "
                                f"(置信度={confidence:.2f}, 原因={reason})")
                else:
                    # 记录拒绝原因
                    reject_reason = reason if reason else (
                        f"置信度不足 ({confidence:.2f} < {VALIDATION_CONFIDENCE_THRESHOLD})"
                        if is_valid else "验证未通过"
                    )
                    logger.info(f"  验证拒绝合并: 新题 {new_id} -> 聚类 {cluster_id} "
                                f"(置信度={confidence:.2f}, 原因={reject_reason})")
                    # 低置信度的有效判定 → 二次人工审核
                    if is_valid and confidence < VALIDATION_CONFIDENCE_THRESHOLD:
                        pair_data = pair_lookup.get((new_id, cluster_id))
                        rejected_for_review.append({
                            "new_id": new_id,
                            "cluster_id": cluster_id,
                            "new_question": pair_data[0]['question'] if pair_data else '',
                            "cluster_question": pair_data[1]['question'] if pair_data else '',
                            "confidence": confidence,
                            "reason": reason,
                        })
            else:
                logger.info(f"  验证拒绝合并: 新题 {new_id} -> 聚类 {cluster_id} (无验证结果)")

        if rejected_for_review:
            logger.warning(
                f"  ⚠ {len(rejected_for_review)} 对合并需要二次人工审核 "
                f"(置信度 < {VALIDATION_CONFIDENCE_THRESHOLD}): "
                + ", ".join(f"新题{r['new_id']}→聚类{r['cluster_id']}(c={r['confidence']:.2f})"
                            for r in rejected_for_review)
            )

        return (validated_matches, confidence_map)

    except Exception as e:
        logger.warning(f"验证合并失败，拒绝所有合并: {e}")
        return ([], {})  # 验证失败时拒绝所有合并，而非返回原始匹配


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


async def calculate_dynamic_recent_days(cat2: str) -> int:
    """根据 cat2 的题目更新频率动态调整 recent_days。

    高频分类（最近 30 天新增 >= 20 题）→ 3 天窗口
    中频分类（最近 30 天新增 5~19 题）→ 7 天窗口（默认）
    低频分类（最近 30 天新增 < 5 题）→ 14 天窗口

    Args:
        cat2: 题目分类

    Returns:
        动态计算的 recent_days
    """
    def _query():
        conn = get_db_connection()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM question_bank "
            "WHERE cat2 = ? AND deleted_at IS NULL "
            "AND created_at > datetime('now', '-30 days')",
            (cat2,)
        ).fetchone()
        return row['cnt'] if row else 0

    try:
        count = await asyncio.to_thread(_query)
        if count >= 20:
            days = 3
            logger.info(f"  [{cat2}] 高频分类（30天内 {count} 题），recent_days={days}")
        elif count >= 5:
            days = 7
        else:
            days = 14
            logger.info(f"  [{cat2}] 低频分类（30天内 {count} 题），recent_days={days}")
        return days
    except Exception as e:
        logger.warning(f"动态调整 recent_days 失败: {e}")
        return RECENT_DAYS


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
            # Embedding 预筛选：从全部 centroid 中选出最可能匹配的 top-K
            filtered_clusters = existing_clusters
            if len(existing_clusters) > _PREFILTER_TOP_K:
                # 对每个新题取 top-K centroid 的并集
                candidate_ids = set()
                for q in new_questions:
                    top_k = prefilter_centroids(
                        query_text=q['question'],
                        centroids=existing_clusters,
                        top_k=_PREFILTER_TOP_K,
                    )
                    candidate_ids.update(c['id'] for c in top_k)
                filtered_clusters = [c for c in existing_clusters if c['id'] in candidate_ids]
                logger.info(f"  [{cat2 or '无分类'}] Embedding 预筛选: {len(existing_clusters)} → {len(filtered_clusters)} 个候选 centroid")

            prompt = MATCH_EXISTING_PROMPT.format(
                existing_clusters=_format_existing_clusters(filtered_clusters),
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
                    validated_matches, _confidence_map = await _validate_merges(
                        phase1_matches, new_questions, existing_clusters, user_id
                    )
                    # 更新 matched 列表，只保留验证通过的
                    validated_new_ids = {str(m.get('new_id')) for m in validated_matches}
                    matched = [m for m in matched if str(m.get('qd_id')) in validated_new_ids or str(m.get('qd_id')) not in matched_cluster_ids]
                    # 更新 unmatched_ids
                    unmatched_ids = {str(q['id']) for q in new_questions} - {str(m.get('qd_id')) for m in matched}

        except Exception as e:
            logger.warning(f"  [{cat2 or '无分类'}] Phase 1 匹配已有聚类失败: {e}")

    # Phase 1.5: 匹配最近 N 天的 frequency=1 题目（动态时间窗口）
    unmatched_questions = [q for q in new_questions if str(q['id']) in unmatched_ids]
    if unmatched_questions and recent_days > 0:
        # 动态调整时间窗口
        effective_days = await calculate_dynamic_recent_days(cat2) if recent_days == RECENT_DAYS else recent_days
        try:
            recent_singletons = await _load_recent_singletons(cat2, days=effective_days)
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
                    logger.info(f"  [{cat2 or '无分类'}] Phase 1.5 匹配最近 {effective_days} 天题目: {len(matched_recent_ids)} 题")

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


# ═══════════════════════════════════════════════════════════════
# 三阶段高效聚类（零 LLM 粗筛 + 批量 LLM 验证）
#
# 行业标准三阶段漏斗（参考 SemDeDup / MinHash-LSH / Milvus）：
#   Stage 1: 精确文本匹配 → 直接合并频率（零成本）
#   Stage 2: Embedding 余弦相似度 → 找候选对（零 LLM 成本）
#   Stage 3: LLM 批量验证 → 一次调用验证所有候选对
#
# 旧方案: 229题 × 3候选 × 1次LLM = 687 次 API 调用
# 新方案: 229题 × FAISS检索 → ~30候选对 → 1次批量LLM = 1 次调用
# ═══════════════════════════════════════════════════════════════

_BATCH_VERIFY_PROMPT = """你是面试题去重专家。以下是一批待验证的面试题对，请判断每一对是否应该合并（频率累加）。

判断标准：
- 核心知识点相同，只是提问角度不同 → 合并
- 相似但不同知识点 → 不合并

可以合并：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"
- "上下文过长怎么办" ≈ "agent怎么获取上下文"

坚决不合并：
- "Redis 缓存穿透" ≠ "Redis 缓存雪崩"
- "MySQL 索引优化" ≠ "MySQL 查询优化"
- "TCP 三次握手" ≠ "TCP 四次挥手"

【待验证的题目对】（共 {count} 对）：
{pairs}

返回 JSON 格式：
{{"results": [{{"pair_id": 1, "merge": true/false, "confidence": 0.0-1.0}}]}}
只返回 JSON。"""


async def cluster_three_stage(
    questions: List[Dict],
    user_id=None,
    similarity_threshold: float = 0.75,
) -> Dict[str, Any]:
    """三阶段高效聚类：精确匹配 → Embedding 粗筛 → LLM 批量验证。

    API 调用次数：1 次（批量验证所有候选对）

    Args:
        questions: 题目列表 [{"id", "question", "cat1", "cat2", "tags", "frequency"}]
        user_id: 用户 ID
        similarity_threshold: Embedding 余弦相似度阈值（粗筛）

    Returns:
        {"merged": [(survivor_id, merged_id, confidence)], "unmatched": [id]}
    """
    import numpy as np
    from app.services.embedding_service import encode_texts, build_index

    merged_pairs = []
    merged_ids = set()

    # ═══════════════════════════════════════════════════════════
    # Stage 1: 精确文本匹配（零成本）
    # ═══════════════════════════════════════════════════════════
    text_map = {}  # question_text -> [ids]
    for q in questions:
        text = (q.get('question') or '').strip()
        if text:
            text_map.setdefault(text, []).append(q['id'])

    stage1_count = 0
    for text, ids in text_map.items():
        if len(ids) < 2:
            continue
        # 保留 frequency 最高的作为存活题
        survivors = [(q['frequency'], q['id']) for q in questions if q['id'] in ids]
        survivors.sort(reverse=True)
        survivor_id = survivors[0][1]
        for _, mid in survivors[1:]:
            if mid not in merged_ids:
                merged_pairs.append((survivor_id, mid, 1.0))
                merged_ids.add(mid)
                stage1_count += 1

    logger.info(f"Stage 1 精确匹配: {stage1_count} 对")

    # ═══════════════════════════════════════════════════════════
    # Stage 2: Embedding 余弦相似度粗筛（零 LLM 成本）
    # ═══════════════════════════════════════════════════════════
    remaining = [q for q in questions if q['id'] not in merged_ids]
    if len(remaining) < 2:
        return {"merged": merged_pairs, "unmatched": [q['id'] for q in remaining]}

    # 编码所有剩余题目（一次性批量编码）
    texts = [q.get('question', '') for q in remaining]
    embeddings = encode_texts(texts)

    # 构建 FAISS 索引
    index = build_index(embeddings)

    # 搜索每个题目的最近邻
    candidate_pairs = []  # [(idx1, idx2, similarity)]
    seen_pairs = set()

    for i in range(len(remaining)):
        q_emb = embeddings[i:i+1]
        k = min(6, len(remaining))  # 最近 5 个邻居
        scores, indices = index.search(q_emb, k)

        for j, (idx, score) in enumerate(zip(indices[0], scores[0])):
            if idx == i or idx >= len(remaining):
                continue
            # 确保 pair 唯一（小 id 在前）
            pair = (min(i, idx), max(i, idx))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            if score >= similarity_threshold:
                candidate_pairs.append((pair[0], pair[1], float(score)))

    # 按相似度降序排列
    candidate_pairs.sort(key=lambda x: x[2], reverse=True)

    logger.info(f"Stage 2 Embedding 粗筛: {len(candidate_pairs)} 候选对 (阈值={similarity_threshold})")

    if not candidate_pairs:
        unmatched = [q['id'] for q in remaining]
        return {"merged": merged_pairs, "unmatched": unmatched}

    # ═══════════════════════════════════════════════════════════
    # Stage 3: LLM 批量验证（1 次 API 调用）
    # ═══════════════════════════════════════════════════════════
    # 构建验证 prompt
    pairs_text = []
    for pi, (i1, i2, sim) in enumerate(candidate_pairs):
        q1 = remaining[i1]
        q2 = remaining[i2]
        pairs_text.append(
            f"对{pi+1}: [{q1['id']}] {q1['question'][:80]}\n"
            f"     [{q2['id']}] {q2['question'][:80]} (相似度={sim:.2f})"
        )

    prompt = _BATCH_VERIFY_PROMPT.format(
        count=len(candidate_pairs),
        pairs="\n\n".join(pairs_text),
    )

    try:
        logger.info(f"Stage 3 LLM 批量验证: {len(candidate_pairs)} 对 (1 次 API 调用)")
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)

        stage3_count = 0
        for pr in result.get("results", []):
            pair_id = pr.get("pair_id", 0) - 1  # 1-indexed → 0-indexed
            if pair_id < 0 or pair_id >= len(candidate_pairs):
                continue
            if not pr.get("merge"):
                continue

            confidence = float(pr.get("confidence", 0.8))
            i1, i2, _ = candidate_pairs[pair_id]
            q1 = remaining[i1]
            q2 = remaining[i2]

            if q1['id'] in merged_ids or q2['id'] in merged_ids:
                continue

            # 保留 frequency 更高的作为存活题
            if q1.get('frequency', 1) >= q2.get('frequency', 1):
                survivor_id, merged_id = q1['id'], q2['id']
            else:
                survivor_id, merged_id = q2['id'], q1['id']

            merged_pairs.append((survivor_id, merged_id, confidence))
            merged_ids.add(merged_id)
            stage3_count += 1

        logger.info(f"Stage 3 验证通过: {stage3_count} 对")

    except Exception as e:
        logger.warning(f"Stage 3 LLM 验证失败: {e}")

    unmatched = [q['id'] for q in remaining if q['id'] not in merged_ids]
    return {"merged": merged_pairs, "unmatched": unmatched}


async def full_recluster_hybrid(
    user_id=None,
    similarity_threshold: float = 0.75,
) -> Dict[str, Any]:
    """全量聚类：三阶段高效聚类（1 次 LLM 调用）。

    Args:
        user_id: 用户 ID
        similarity_threshold: Embedding 余弦相似度阈值

    Returns:
        {"total": int, "merged": int, "remaining": int}
    """
    def _load_all():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question, cat1, cat2, tags, frequency "
            "FROM question_bank "
            "WHERE deleted_at IS NULL AND status = 'approved' AND duplicate_of IS NULL "
            "ORDER BY frequency DESC, id"
        ).fetchall()
        return [dict(r) for r in rows]

    questions = await _scan_async(_load_all)
    if not questions:
        return {"total": 0, "merged": 0, "remaining": 0}

    logger.info(f"全量聚类开始: {len(questions)} 题")

    result = await cluster_three_stage(
        questions, user_id=user_id, similarity_threshold=similarity_threshold
    )

    # 执行合并
    for survivor_id, merged_id, confidence in result['merged']:
        def _do_merge(s=survivor_id, m=merged_id, c=confidence):
            conn = get_db_connection()
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "UPDATE question_bank SET duplicate_of = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (s, m)
                )
                conn.execute(
                    "UPDATE question_bank SET frequency = frequency + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (s,)
                )
                conn.execute(
                    "INSERT INTO merge_history "
                    "(survivor_id, merged_ids, merged_questions, pre_snapshot, "
                    "operation_type, phase, confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (s, json.dumps([m]),
                     json.dumps([next((q['question'] for q in questions if q['id'] == m), '')]),
                     json.dumps({"merged_id": m}),
                     'three_stage', 'full_recluster', c)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        await _scan_async(_do_merge)

    total = len(questions)
    merged = len(result['merged'])
    remaining = len(result['unmatched'])

    logger.info(f"全量聚类完成: 总数={total}, 合并={merged}, 剩余={remaining}")
    return {"total": total, "merged": merged, "remaining": remaining}

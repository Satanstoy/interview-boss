"""流式增量聚类服务：匹配已有聚类 + 内部聚类新题"""
import asyncio
import json
import logging
import re
from typing import List, Dict, Any

from app.db.connection import get_db_connection
from app.services.llm import _call_llm_with_retry, _extract_json
from app.services.embedding_service import prefilter_centroids, prefilter_centroids_batch

logger = logging.getLogger("interview-boss")

MAX_CONCURRENCY = 8  # 增加并发
RECENT_DAYS = 7  # 默认匹配最近 7 天的 frequency=1 题目
VALIDATION_CONFIDENCE_THRESHOLD = 0.8  # 验证置信度阈值
DIRECT_ACCEPT_CONFIDENCE_THRESHOLD = 0.92  # 高置信同类匹配直接通过
VALIDATION_BATCH_SIZE = 20  # 二次验证分块，避免长 JSON 漏项
_PREFILTER_TOP_K = 30  # Embedding 预筛选保留的候选 centroid 数量


def _extract_id(raw) -> str:
    """从 LLM 返回值提取纯数字 ID（兜底去掉「新题」「聚类」等前缀）"""
    import re as _re
    s = str(raw or "").strip()
    m = _re.search(r'\d+', s)
    return m.group(0) if m else s


def _normalize_question_text(text: str) -> str:
    """用于零成本精确命中的轻量文本标准化。"""
    text = (text or "").strip().lower()
    replacements = {
        "？": "?",
        "！": "!",
        "，": ",",
        "。": ".",
        "：": ":",
        "；": ";",
        "（": "(",
        "）": ")",
        "、": ",",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"[\s\?？!！。.,，、:：;；]+", "", text)


def _safe_confidence(match: Dict) -> float | None:
    try:
        if match.get("confidence") is None:
            return None
        return float(match.get("confidence"))
    except (TypeError, ValueError):
        return None


# ──────────────────────────── Prompts ────────────────────────────

MATCH_EXISTING_PROMPT = """你是一个面试题去重专家。你的任务是将一批【新题目】归类到【已有标准题库】中。

注意：【待匹配的新题目】是一个不超过 40 道题的微批次，请逐题判断是否与已有题库中的某道题真正重复。

匹配判断准则（核心）：
如果两道题考察的**核心知识点相同**，只是提问角度、详略、场景不同，就应该合并。
如果一道题是另一道题的**子集或超集**，且答案高度重叠，也应该合并。
如果两道题虽然属于同一技术领域，但需要**完全不同的一套答案**来回答，则不合并。

✅ 可以合并的真实案例：
- "多智能体框架你了解哪几个？" → "多智能体有哪些形式？"（同一问题的不同说法）
- "你的 Agent 死循环了怎么办？" → "当Agent执行一个较长链路，出现死循环，如何做自动恢复？"（同一场景题）
- "Workflow 和 Agent 到底有什么区别？" → "Agent Loop 是什么？和普通工作流有什么区别？"（核心都在对比 workflow 与 agent）
- "介绍一下RAG的具体流程" → "RAG是怎么做的" → "RAG各个部分怎么做（端到端设计）"（同一问题不同详略）
- "MCP 和 Function Calling 有什么区别？" → "function call和工具调用有什么区别" → "mcp和tool的区别"（都围绕 MCP vs FC vs Tool 的对比）
- "挑一个项目介绍" → "介绍项目"（完全等价）
- "上下文过长怎么办" → "token溢出怎么办" → "短期记忆如何处理上下文爆炸"（都涉及上下文/窗口溢出处理）
- "SDD和skills的区别" → "mcp和skill" → "skill和prompt区别"（都涉及 Skill 机制的定位与对比）
- "为什么选择用deepseek" → "模型选择" → "你用的是哪个基模型？"（都问模型选型理由）

❌ 坚决不合并的真实案例：
- 「Redis 缓存穿透」≠「Redis 缓存雪崩」（穿透是查不存在的 key，雪崩是大面积 key 同时过期，解法完全不同）
- 「volatile关键字的作用」≠「Java JUC、JVM相关知识」（volatile 只是 JUC 一个知识点，"JUC 相关知识"太宽泛，可包含线程池/AQS/CAS 等完全不同话题）
- 「Agent Memory 怎么设计」≠「上下文漂移」（Memory 设计关注存储结构和检索策略，上下文漂移关注对话偏离主题的检测与纠正）
- 「解释一下token」≠「Token 成本问题」（token 的定义/分词 vs token 计费/成本优化，需要不同答案）
- 「Redis熟悉不熟悉」≠「Redis Lua有了解吗」（过于宽泛的开场白 ≠ 具体子技术的考察）
- 「TCP 三次握手」≠「TCP 四次挥手」（建立连接 vs 断开连接，流程完全不同）
- 「高并发限流」≠「研究生方向」（完全不相关领域）

**重要原则：真正重复的题目应该合并，不要遗漏。只在核心知识点确实不同时才拒绝。**

【已有标准题库】（格式：[聚类ID] 代表题目）：
{existing_clusters}

【待匹配的新题目】（微批次，共 {count} 题）：
{new_questions}

请输出 JSON 格式，列出成功匹配的结果。每个匹配必须附带 confidence（0~1 小数，表示你对该匹配的确信程度）。new_id 和 cluster_id 必须是纯数字 ID，不要添加任何前缀。如果没有匹配项，输出空数组。
{{"matches": [{{"new_id": "6262", "cluster_id": "5878", "confidence": 0.95}}]}}
只输出 JSON，不要解释。"""

CLUSTER_NEW_PROMPT = """你是一个面试题聚类专家。以下是一个不超过 40 道题的微批次，请在它们内部寻找**真正重复**的题目并进行合并。

合并判断准则（核心）：
如果两道题考察的**核心知识点相同**，只是提问角度、详略、场景不同，就应该合并。
如果一道题是另一道题的**子集或超集**，且答案高度重叠，也应该合并。
如果两道题虽然属于同一技术领域，但需要**完全不同的一套答案**来回答，则不合并。

✅ 可以合并的真实案例：
- "多智能体框架你了解哪几个？" + "多智能体有哪些形式？"（同一问题的不同说法）
- "你的 Agent 死循环了怎么办？" + "当Agent执行一个较长链路，出现死循环，如何做自动恢复？"（同一场景题）
- "介绍一下RAG的具体流程" + "RAG是怎么做的" + "RAG各个部分怎么做（端到端设计）"（同一问题不同详略）
- "MCP 和 Function Calling 有什么区别？" + "function call和工具调用有什么区别" + "mcp和tool的区别"（都围绕 MCP vs FC vs Tool 的对比）
- "上下文过长怎么办" + "token溢出怎么办" + "短期记忆如何处理上下文爆炸"（都涉及上下文/窗口溢出处理）
- "SDD和skills的区别" + "mcp和skill" + "skill和prompt区别"（都涉及 Skill 机制的定位与对比）
- "为什么选择用deepseek" + "模型选择" + "你用的是哪个基模型？"（都问模型选型理由）

❌ 坚决不合并的真实案例：
- 「Redis 缓存穿透」≠「Redis 缓存雪崩」（穿透是查不存在的 key，雪崩是大面积 key 同时过期，解法完全不同）
- 「volatile关键字的作用」≠「Java JUC、JVM相关知识」（volatile 只是 JUC 一个知识点，"JUC 相关知识"太宽泛，可包含线程池/AQS/CAS 等完全不同话题）
- 「Agent Memory 怎么设计」≠「上下文漂移」（Memory 设计关注存储结构和检索策略，上下文漂移关注对话偏离主题的检测与纠正）
- 「解释一下token」≠「Token 成本问题」（token 的定义/分词 vs token 计费/成本优化，需要不同答案）
- 「Redis熟悉不熟悉」≠「Redis Lua有了解吗」（过于宽泛的开场白 ≠ 具体子技术的考察）
- 「TCP 三次握手」≠「TCP 四次挥手」（建立连接 vs 断开连接，流程完全不同）

**重要原则：真正重复的题目应该合并，不要遗漏。只在核心知识点确实不同时才拒绝。**

【待聚类的新题目】（微批次，共 {count} 题）：
{unmatched_questions}

请输出 JSON 格式。只有确实重复的才放入 clusters，独立的题目不需要输出。
{{"clusters": [{{"ids": ["题号1", "题号2"], "representative": "选取其中表述最清晰的一道题作为代表"}}]}}
只输出 JSON，不要解释。"""


VALIDATE_MERGES_PROMPT = """你是一个面试题去重验证专家。以下是一批待合并的题目对，请验证每一对是否真的应该合并。

验证标准：
如果两道题考察的**核心知识点相同**，只是提问角度、详略、场景不同，应该合并（valid=true）。
如果一道题是另一道题的**子集或超集**，且准备答案时高度重叠，应该合并（valid=true）。
如果两道题虽然属于同一技术领域，但需要**完全不同的一套答案**来回答，不合并（valid=false）。

✅ 应该通过验证的真实案例（valid=true, confidence>=0.9）：
- "多智能体框架你了解哪几个？" + "多智能体有哪些形式？" → 同一问题，不同说法
- "你的 Agent 死循环了怎么办？" + "当Agent执行一个较长链路，出现死循环，如何做自动恢复？" → 同一场景题
- "Workflow 和 Agent 到底有什么区别？" + "Agent Loop 是什么？和普通工作流有什么区别？" → 核心都在对比 workflow 与 agent
- "MCP 和 Function Calling 有什么区别？" + "function call和工具调用有什么区别" → 都围绕 MCP vs FC vs Tool
- "挑一个项目介绍" + "介绍项目" → 完全等价
- "上下文过长怎么办" + "token溢出怎么办" → 都涉及上下文/窗口溢出处理
- "SDD和skills的区别" + "mcp和skill" → 都涉及 Skill 机制的定位与对比
- "为什么选择用deepseek" + "模型选择" → 都问模型选型理由
- "介绍一下RAG的具体流程" + "RAG是怎么做的" → 同一问题不同详略

❌ 应该拒绝合并的真实案例（valid=false）：
- 「Redis 缓存穿透」≠「Redis 缓存雪崩」→ 穿透是查不存在的 key，雪崩是大面积 key 同时过期，解法完全不同
- 「volatile关键字的作用」≠「Java JUC、JVM相关知识」→ volatile 只是 JUC 一个知识点，"JUC 相关知识"太宽泛
- 「Agent Memory 怎么设计」≠「上下文漂移」→ Memory 设计 vs 偏离检测，完全不同话题
- 「解释一下token」≠「Token 定价/成本问题」→ token 的定义 vs token 计费，需要不同答案
- 「Redis熟悉不熟悉」≠「Redis Lua有了解吗」→ 过于宽泛的开场白 ≠ 具体子技术考察
- 「TCP 三次握手」≠「TCP 四次挥手」→ 建立连接 vs 断开连接

【待验证的题目对】：
{pairs}

请输出 JSON 格式，列出每一对的验证结果。confidence 为 0~1 之间的小数，表示你对该合并判断的确信程度。
new_id 和 cluster_id 必须是纯数字 ID，不要添加任何前缀。
{{"validations": [{{"new_id": "6370", "cluster_id": "6289", "valid": true, "confidence": 0.95, "reason": "判断理由（简短）"}}]}}
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
    validation_items = []
    pair_lookup = {}
    for match in matches:
        new_id = _extract_id(match.get('new_id', ''))
        cluster_id = _extract_id(match.get('cluster_id', ''))

        new_q = new_q_map.get(new_id)
        cluster_q = cluster_map.get(cluster_id)

        if new_q and cluster_q:
            validation_items.append({
                "match": match,
                "new_id": new_id,
                "cluster_id": cluster_id,
                "pair_text": f"题目A (ID={new_id}): {new_q['question']}\n题目B (ID={cluster_id}): {cluster_q['question']}",
            })
            pair_lookup[(new_id, cluster_id)] = (new_q, cluster_q)

    if not validation_items:
        # 没有可验证的对时，拒绝所有匹配（而非放行）
        logger.warning(f"[验证] 无法构建验证对 ({len(matches)} 匹配被拒绝)")
        return ([], {})

    chunks = [
        validation_items[i:i + VALIDATION_BATCH_SIZE]
        for i in range(0, len(validation_items), VALIDATION_BATCH_SIZE)
    ]

    async def _validate_chunk(chunk):
        prompt = VALIDATE_MERGES_PROMPT.format(
            pairs="\n\n".join(item["pair_text"] for item in chunk)
        )
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)
        return result.get("validations", [])

    try:
        if len(chunks) == 1:
            validations = await _validate_chunk(chunks[0])
        else:
            semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

            async def _guarded_validate(chunk):
                async with semaphore:
                    try:
                        return await _validate_chunk(chunk)
                    except Exception as e:
                        logger.warning(f"验证分块失败，拒绝该分块 {len(chunk)} 对合并: {e}")
                        return []

            chunk_results = await asyncio.gather(
                *[_guarded_validate(chunk) for chunk in chunks],
                return_exceptions=False
            )
            validations = [
                validation
                for chunk_validations in chunk_results
                for validation in chunk_validations
            ]

        # 过滤验证通过的合并（带置信度阈值）
        validated_matches = []
        confidence_map = {}
        rejected_for_review = []

        for match in matches:
            new_id = _extract_id(match.get('new_id', ''))
            cluster_id = _extract_id(match.get('cluster_id', ''))

            # 查找对应的验证结果（用纯数字 ID 匹配，兼容 LLM 带前缀）
            validation = next(
                (v for v in validations
                 if _extract_id(v.get('new_id')) == new_id and _extract_id(v.get('cluster_id')) == cluster_id),
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


def _build_matched_item(q: Dict, cluster_id: str, cat2: str) -> Dict:
    return {
        "qd_id": q['id'],
        "cluster_id": cluster_id,
        "question": q['question'],
        "cat1": q.get('cat1', ''),
        "cat2": q.get('cat2', cat2),
        "tags": q.get('tags', ''),
        "diff_tag": q.get('diff_tag', ''),
        "url": q.get('url', ''),
        "company": q.get('company', ''),
        "round": q.get('round', ''),
    }


def _apply_exact_candidate_matches(
    cat2: str,
    questions: List[Dict],
    candidates: List[Dict],
    unmatched_ids: set[str],
) -> tuple[List[Dict], set[str]]:
    """对完全相同的问题文本零成本匹配，优先使用已成型聚类。"""
    candidate_by_text = {}
    for c in candidates:
        key = _normalize_question_text(c.get("question", ""))
        if key and key not in candidate_by_text:
            candidate_by_text[key] = str(c["id"])

    matched = []
    matched_ids = set()
    for q in questions:
        qid = str(q["id"])
        if qid not in unmatched_ids:
            continue
        cid = candidate_by_text.get(_normalize_question_text(q.get("question", "")))
        if not cid:
            continue
        matched.append(_build_matched_item(q, cid, cat2))
        matched_ids.add(qid)

    return matched, matched_ids


def _extract_raw_matches(result: Dict, unmatched_ids: set[str]) -> List[Dict]:
    raw_matches = []
    processed_new_ids = set()
    for m in result.get("matches", []):
        nid = _extract_id(m.get("new_id", ""))
        cid = _extract_id(m.get("cluster_id", "")) if m.get("cluster_id") is not None else None
        if not cid and m.get("target_id") is not None:
            cid = _extract_id(m.get("target_id", ""))
        if nid in unmatched_ids and nid not in processed_new_ids and cid is not None:
            processed_new_ids.add(nid)
            normalized = dict(m)
            normalized["new_id"] = nid
            normalized["cluster_id"] = cid
            raw_matches.append(normalized)
    return raw_matches


def _partition_matches_by_risk(matches: List[Dict], cat2: str) -> tuple[List[Dict], List[Dict]]:
    direct_matches = []
    needs_validation = []
    conservative_cat = cat2 in ("", "其他")
    for m in matches:
        confidence = _safe_confidence(m)
        if (
            confidence is not None
            and confidence >= DIRECT_ACCEPT_CONFIDENCE_THRESHOLD
            and not conservative_cat
        ):
            direct_matches.append(m)
        elif confidence is None or confidence >= VALIDATION_CONFIDENCE_THRESHOLD:
            needs_validation.append(m)
    return direct_matches, needs_validation


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
    if isinstance(existing_clusters, dict):
        existing_clusters = existing_clusters.get(cat2, [])
    existing_clusters = existing_clusters or []

    matched = []
    unmatched_ids = {str(q['id']) for q in new_questions}

    filtered_clusters = existing_clusters
    if existing_clusters:
        try:
            if len(existing_clusters) > _PREFILTER_TOP_K:
                batch_results = prefilter_centroids_batch(
                    query_texts=[q['question'] for q in new_questions],
                    centroids=existing_clusters,
                    top_k=_PREFILTER_TOP_K,
                )
                candidate_ids = set()
                for qi_results in batch_results.values():
                    candidate_ids.update(c['id'] for c in qi_results)
                filtered_clusters = [c for c in existing_clusters if c['id'] in candidate_ids]
                logger.info(f"  [{cat2 or '无分类'}] Embedding 预筛选: {len(existing_clusters)} → {len(filtered_clusters)} 个候选 centroid")
        except Exception as e:
            logger.warning(f"  [{cat2 or '无分类'}] Embedding 预筛选失败，降级为全量候选: {e}")
            filtered_clusters = existing_clusters

    recent_singletons = []
    effective_days = recent_days
    if recent_days > 0:
        effective_days = await calculate_dynamic_recent_days(cat2) if recent_days == RECENT_DAYS else recent_days
        try:
            recent_singletons = await _load_recent_singletons(cat2, days=effective_days)
        except Exception as e:
            logger.warning(f"  [{cat2 or '无分类'}] 加载最近题目失败: {e}")

    all_exact_candidates = []
    seen_candidate_ids = set()
    for c in list(existing_clusters or []) + list(recent_singletons or []):
        cid = str(c.get("id"))
        if cid not in seen_candidate_ids:
            all_exact_candidates.append(c)
            seen_candidate_ids.add(cid)

    exact_matches, exact_matched_ids = _apply_exact_candidate_matches(
        cat2, new_questions, all_exact_candidates, unmatched_ids
    )
    if exact_matches:
        matched.extend(exact_matches)
        unmatched_ids -= exact_matched_ids
        logger.info(f"  [{cat2 or '无分类'}] 精确文本命中候选: {len(exact_matches)} 题")

    candidate_pool = []
    seen_candidate_ids = set()
    for c in list(filtered_clusters or []) + list(recent_singletons or []):
        cid = str(c.get("id"))
        if cid not in seen_candidate_ids:
            candidate_pool.append(c)
            seen_candidate_ids.add(cid)

    unmatched_questions = [q for q in new_questions if str(q['id']) in unmatched_ids]
    if candidate_pool and unmatched_questions:
        try:
            prompt = MATCH_EXISTING_PROMPT.format(
                existing_clusters=_format_existing_clusters(candidate_pool),
                new_questions=_format_new_questions(unmatched_questions),
                count=len(unmatched_questions),
            )
            content = await _call_llm_with_retry(
                prompt, response_format={"type": "json_object"}, user_id=user_id
            )
            result = _extract_json(content)
            raw_matches = _extract_raw_matches(result, unmatched_ids)
            direct_matches, matches_to_validate = _partition_matches_by_risk(raw_matches, cat2)

            if matches_to_validate:
                logger.info(f"  [{cat2 or '无分类'}] 中置信/保守匹配需二次验证: {len(matches_to_validate)} 题")
                validated_matches, _confidence_map = await _validate_merges(
                    matches_to_validate, unmatched_questions, candidate_pool, user_id
                )
            else:
                validated_matches = []

            accepted_matches = list(direct_matches) + list(validated_matches)
            accepted_ids = set()
            q_by_id = {str(q['id']): q for q in unmatched_questions}
            for m in accepted_matches:
                nid = _extract_id(m.get("new_id", ""))
                cid = _extract_id(m.get("cluster_id", "")) if m.get("cluster_id") is not None else None
                q = q_by_id.get(nid)
                if not q or not cid or nid in accepted_ids:
                    continue
                accepted_ids.add(nid)
                matched.append(_build_matched_item(q, cid, cat2))

            unmatched_ids -= accepted_ids
            if accepted_ids:
                logger.info(
                    f"  [{cat2 or '无分类'}] 候选池匹配: {len(accepted_ids)} 题 "
                    f"(高置信直通={len(direct_matches)}, 验证通过={len(validated_matches)}, "
                    f"最近窗口={effective_days if recent_days > 0 else 0}天)"
                )

        except Exception as e:
            logger.warning(f"  [{cat2 or '无分类'}] 候选池匹配失败: {e}")

    # Phase 2: 剩余新题内部聚类
    unmatched_questions = [q for q in new_questions if str(q['id']) in unmatched_ids]
    new_clusters = await _cluster_unmatched(unmatched_questions, user_id)

    return {"matched": matched, "new_clusters": new_clusters}


async def _cluster_unmatched(unmatched_questions, user_id):
    """将未匹配的新题进行内部聚类（带 embedding 门控）"""
    _MIN_CLUSTER_SIMILARITY = 0.6  # 聚类内最低平均相似度阈值

    if len(unmatched_questions) < 2:
        return [{"ids": [str(q['id'])], "representative": q['question'], "items": [q]}
                for q in unmatched_questions]

    exact_groups = {}
    for q in unmatched_questions:
        key = _normalize_question_text(q.get("question", ""))
        if key:
            exact_groups.setdefault(key, []).append(q)

    exact_clusters = []
    exact_clustered_ids = set()
    for group in exact_groups.values():
        if len(group) < 2:
            continue
        ids = [str(q["id"]) for q in group]
        exact_clustered_ids.update(ids)
        exact_clusters.append({
            "ids": ids,
            "representative": max((q["question"] for q in group), key=len),
            "items": group,
        })

    if exact_clusters:
        unmatched_questions = [
            q for q in unmatched_questions
            if str(q["id"]) not in exact_clustered_ids
        ]
        logger.info(f"    内部聚类精确文本命中: {len(exact_clusters)} 个聚类")
        if len(unmatched_questions) < 2:
            singles = [
                {"ids": [str(q['id'])], "representative": q['question'], "items": [q]}
                for q in unmatched_questions
            ]
            return exact_clusters + singles

    prompt = CLUSTER_NEW_PROMPT.format(
        unmatched_questions=_format_new_questions(unmatched_questions),
        count=len(unmatched_questions),
    )

    try:
        content = await _call_llm_with_retry(
            prompt, response_format={"type": "json_object"}, user_id=user_id
        )
        result = _extract_json(content)

        # 预编码所有题目 embedding（一次批量调用）
        try:
            from app.services import embedding_service
            import numpy as np
            texts = [q['question'] for q in unmatched_questions]
            embeddings = embedding_service.encode_texts(texts)
            # hash fallback 只适合测试/降级检索，不能否决 LLM 的语义聚类。
            if getattr(embedding_service, "_SESSION", None) is None:
                emb_map = {}
            else:
                emb_map = {str(q['id']): embeddings[i] for i, q in enumerate(unmatched_questions)}
        except Exception:
            emb_map = {}

        clusters = list(exact_clusters)
        clustered_ids = set()

        for c in result.get("clusters", []):
            ids = [str(i) for i in c.get("ids", [])]
            if len(ids) >= 2:
                # embedding 门控：检查聚类内平均相似度
                if emb_map and all(i in emb_map for i in ids):
                    sims = []
                    for i in range(len(ids)):
                        for j in range(i + 1, len(ids)):
                            sim = float(np.dot(emb_map[ids[i]], emb_map[ids[j]]))
                            sims.append(sim)
                    avg_sim = sum(sims) / len(sims) if sims else 0
                    if avg_sim < _MIN_CLUSTER_SIMILARITY:
                        logger.info(f"    embedding 门控拒绝: avg_sim={avg_sim:.3f} < {_MIN_CLUSTER_SIMILARITY}, "
                                    f"拆散聚类 {ids}")
                        continue

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
            new_id = _extract_id(m.get("new_id"))
            cluster_id = _extract_id(m.get("cluster_id"))
            try:
                cluster_id_int = int(cluster_id) if cluster_id else None
                new_id_int = int(new_id) if new_id else None
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
# 三阶段聚类 V2（embedding 预组织 + LLM 语义分组核心）
#
# 改进点（参考 ClusterFusion 2025 论文思路）：
#   1. 降低 embedding 阈值 0.75→0.55（粗筛不决策）
#   2. 按 cat2 分组聚类（跨领域不干扰）
#   3. 增大 FAISS top-K 5→10（提高传递性召回）
#   4. LLM 分组聚类替代简化批量验证（语义决策核心）
#   5. Union-find 传递性合并
# ═══════════════════════════════════════════════════════════════

_V2_GROUP_PROMPT = """你是面试题去重专家。以下是一个分类（{cat2}）下的面试题候选组，请将其中语义真正重复的题目分到同一组。

判断准则（核心）：
如果两道题考察的**核心知识点完全相同**，只是提问角度不同，才应该合并。

可以合并（同一技术点的不同提问角度）：
- "TCP为什么是三次握手" ≈ "TCP三次握手的作用"
- "介绍一下 ReAct" ≈ "ReAct 范式的原理是什么"
- "Redis 持久化方式有哪些？" ≈ "Redis 的 RDB 和 AOF 持久化有什么区别？"
- "volatile关键字的作用" ≈ "Java 中 volatile 有什么用"
- "上下文过长怎么办" ≈ "agent 怎么管理长上下文"

**坚决不合并（即使在同一分类下）：**
- 不同技术主题：「数据库优化」≠「项目介绍」≠「代码质量」
- 不同业务场景：「秒杀系统」≠「数据同步」≠「实习经历」
- 泛化问题：「项目介绍」「拷打项目」这种泛化问题不要和其他具体问题合并
- 只是都涉及"AI"但主题不同：「AI工具使用」≠「AI辅助编程质量」≠「AI前沿动态」

**⚠️ 特别注意：**
- 如果题目之间没有明确的知识点重叠，宁可不合并
- "其他"分类下的题目通常不相关，要特别谨慎
- 独立题目不需要输出，不要强行找关联

【待聚类的题目】（分类：{cat2}，共 {count} 题）：
{questions}

返回 JSON 格式：
{{"groups": [{{"ids": ["题号1", "题号2"], "representative": "表述最清晰的代表题"}}]}}
只返回 JSON。没有可合并的就返回 {{"groups": []}}"""

_V2_SIMILARITY_THRESHOLD = 0.60  # V2 embedding 粗筛阈值
_V2_FAISS_TOP_K = 10  # V2 FAISS 最近邻数


def _union_find(parent: dict, x):
    """Find with path compression."""
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union_merge(parent: dict, rank: dict, a, b):
    """Union by rank."""
    ra, rb = _union_find(parent, a), _union_find(parent, b)
    if ra == rb:
        return
    if rank[ra] < rank[rb]:
        ra, rb = rb, ra
    parent[rb] = ra
    if rank[ra] == rank[rb]:
        rank[ra] += 1


async def cluster_three_stage_v2(
    questions: List[Dict],
    user_id=None,
    similarity_threshold: float = _V2_SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """三阶段聚类 V2：精确匹配 → Embedding 粗筛 → 按 cat2 LLM 语义分组。

    改进：
    - 降低 embedding 阈值（0.75→0.55），粗筛不决策
    - 按 cat2 分组，每组独立 LLM 聚类
    - 增大 FAISS top-K（5→10）
    - LLM 语义分组替代简化批量验证
    - Union-find 传递性合并

    Args:
        questions: [{"id", "question", "cat1", "cat2", "tags", "frequency"}]
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
    text_map = {}
    for q in questions:
        text = (q.get('question') or '').strip()
        if text:
            text_map.setdefault(text, []).append(q['id'])

    stage1_count = 0
    for text, ids in text_map.items():
        if len(ids) < 2:
            continue
        survivors = [(q['frequency'], q['id']) for q in questions if q['id'] in ids]
        survivors.sort(reverse=True)
        survivor_id = survivors[0][1]
        for _, mid in survivors[1:]:
            if mid not in merged_ids:
                merged_pairs.append((survivor_id, mid, 1.0))
                merged_ids.add(mid)
                stage1_count += 1

    logger.info(f"[V2] Stage 1 精确匹配: {stage1_count} 对")

    # ═══════════════════════════════════════════════════════════
    # Stage 2: Embedding 粗筛 + 按 cat2 分组
    # ═══════════════════════════════════════════════════════════
    remaining = [q for q in questions if q['id'] not in merged_ids]
    if len(remaining) < 2:
        return {"merged": merged_pairs, "unmatched": [q['id'] for q in remaining]}

    # 编码所有剩余题目
    texts = [q.get('question', '') for q in remaining]
    embeddings = encode_texts(texts)

    # 构建 FAISS 索引
    index = build_index(embeddings)

    # 搜索每个题目的最近邻（top-K=10）
    candidate_pairs = []
    seen_pairs = set()

    for i in range(len(remaining)):
        q_emb = embeddings[i:i+1]
        k = min(_V2_FAISS_TOP_K, len(remaining))
        scores, indices = index.search(q_emb, k)

        for j, (idx, score) in enumerate(zip(indices[0], scores[0])):
            idx = int(idx)
            if idx == i or idx >= len(remaining):
                continue
            pair = (min(i, idx), max(i, idx))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            if score >= similarity_threshold:
                candidate_pairs.append((pair[0], pair[1], float(score)))

    candidate_pairs.sort(key=lambda x: x[2], reverse=True)

    logger.info(f"[V2] Stage 2 Embedding 粗筛: {len(candidate_pairs)} 候选对 (阈值={similarity_threshold})")

    if not candidate_pairs:
        unmatched = [q['id'] for q in remaining]
        return {"merged": merged_pairs, "unmatched": unmatched}

    # 按 cat2 分组候选对
    cat2_candidates = {}  # cat2 -> set of question indices
    for i1, i2, sim in candidate_pairs:
        cat2_1 = remaining[i1].get('cat2', '') or ''
        cat2_2 = remaining[i2].get('cat2', '') or ''
        # 同 cat2 的对归入该 cat2
        if cat2_1 == cat2_2:
            cat2 = cat2_1
        else:
            # 跨 cat2 的对：保守处理，归入各自 cat2
            cat2 = cat2_1
        cat2_candidates.setdefault(cat2, set())
        cat2_candidates[cat2].add(i1)
        cat2_candidates[cat2].add(i2)
        if cat2_1 != cat2_2:
            cat2_candidates.setdefault(cat2_2, set())
            cat2_candidates[cat2_2].add(i2)

    # ═══════════════════════════════════════════════════════════
    # Stage 3: 按 cat2 分组 LLM 语义聚类
    # ═══════════════════════════════════════════════════════════
    parent = {}
    rank = {}

    # 并发处理所有 cat2 组
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _process_cat2_group(cat2, idx_set):
        """处理单个 cat2 组的 LLM 分组"""
        idx_list = sorted(idx_set)
        if len(idx_list) < 2:
            return

        # "其他"分类跳过（是兜底分类，容易误合并）
        if cat2 in ('其他', ''):
            logger.info(f"[V2] Stage 3 [{cat2 or '未分类'}] 跳过（兜底分类，避免误合并）")
            return

        # 初始化 union-find
        for idx in idx_list:
            if idx not in parent:
                parent[idx] = idx
                rank[idx] = 0

        # 构建 prompt
        q_list = []
        for idx in idx_list:
            q = remaining[idx]
            q_list.append(f"[{q['id']}] {q.get('question', '')}")
        questions_text = "\n".join(q_list)

        prompt = _V2_GROUP_PROMPT.format(
            cat2=cat2 or '未分类',
            count=len(idx_list),
            questions=questions_text,
        )

        async with semaphore:
            try:
                content = await _call_llm_with_retry(
                    prompt, response_format={"type": "json_object"}, user_id=user_id
                )
                result = _extract_json(content)

                for group in result.get("groups", []):
                    ids = [str(i) for i in group.get("ids", [])]
                    if len(ids) < 2:
                        continue
                    # 找到对应的 remaining index
                    id_to_idx = {str(remaining[idx]['id']): idx for idx in idx_list}
                    group_indices = [id_to_idx[sid] for sid in ids if sid in id_to_idx]
                    if len(group_indices) < 2:
                        continue
                    # Union-find 合并
                    for gi in group_indices[1:]:
                        _union_merge(parent, rank, group_indices[0], gi)

                logger.info(f"[V2] Stage 3 [{cat2 or '未分类'}] LLM 分组完成")

            except Exception as e:
                logger.warning(f"[V2] Stage 3 [{cat2 or '未分类'}] LLM 分组失败: {e}")

    # 并发执行所有 cat2 组
    await asyncio.gather(*[_process_cat2_group(cat2, idx_set) for cat2, idx_set in cat2_candidates.items()])

    # 从 union-find 提取合并结果
    clusters = {}
    for idx in parent:
        root = _union_find(parent, idx)
        clusters.setdefault(root, []).append(idx)

    for root, members in clusters.items():
        if len(members) < 2:
            continue
        # 选 frequency 最高的作为 survivor
        member_qs = [(remaining[idx].get('frequency', 1), remaining[idx]['id'], idx) for idx in members]
        member_qs.sort(reverse=True)
        survivor_id = member_qs[0][1]
        for _, mid, mid_idx in member_qs[1:]:
            if mid not in merged_ids:
                merged_pairs.append((survivor_id, mid, 0.9))
                merged_ids.add(mid)

    logger.info(f"[V2] Stage 3 总合并: {len(merged_pairs) - stage1_count} 对 (传递性合并后)")

    unmatched = [q['id'] for q in remaining if q['id'] not in merged_ids]
    return {"merged": merged_pairs, "unmatched": unmatched}


async def full_recluster_hybrid(
    user_id=None,
    similarity_threshold: float = _V2_SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """全量聚类：V2 三阶段聚类（按 cat2 分组 + LLM 语义分组）。

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

    result = await cluster_three_stage_v2(
        questions, user_id=user_id, similarity_threshold=similarity_threshold
    )

    # 构建 lookup 避免 O(N*M) 线性扫描
    question_lookup = {q['id']: q['question'] for q in questions}

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
                     json.dumps([question_lookup.get(m, '')]),
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

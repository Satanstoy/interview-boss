"""增量匹配：process_incremental_batch + match_new_questions"""

import asyncio
import logging
import os
from typing import List, Dict, Any

import numpy as np

from app.db.connection import get_db_connection
from app.core.config import (
    CLUSTER_MAX_CONCURRENCY,
    CLUSTER_RECENT_DAYS,
    CLUSTER_VALIDATION_BATCH,
    CLUSTER_PREFILTER_TOP_K,
)
from app.services.llm import _call_llm_with_retry, _extract_json
from app.services.embedding_service import (
    prefilter_centroids,
    prefilter_centroids_batch,
)
from app.services.clustering.prompts import (
    MATCH_EXISTING_PROMPT,
    VALIDATE_MERGES_PROMPT,
    VALIDATION_CONFIDENCE_THRESHOLD,
    DIRECT_ACCEPT_CONFIDENCE_THRESHOLD,
)
from app.services.clustering.clusterer import (
    _cluster_unmatched,
    _normalize_question_text,
    _format_new_questions,
)
from app.services.backpressure import matcher_semaphore

logger = logging.getLogger("interview-boss")

MAX_CONCURRENCY = CLUSTER_MAX_CONCURRENCY
RECENT_DAYS = CLUSTER_RECENT_DAYS
VALIDATION_BATCH_SIZE = CLUSTER_VALIDATION_BATCH
_PREFILTER_TOP_K = CLUSTER_PREFILTER_TOP_K


# ──────────────────────────── 工具函数 ────────────────────────────


def _extract_id(raw) -> str:
    """从 LLM 返回值提取纯数字 ID（兜底去掉「新题」「聚类」等前缀）"""
    import re as _re

    s = str(raw or "").strip()
    m = _re.search(r"\d+", s)
    return m.group(0) if m else s


def _safe_confidence(match: Dict) -> float | None:
    try:
        if match.get("confidence") is None:
            return None
        return float(match.get("confidence"))
    except (TypeError, ValueError):
        return None


def _build_matched_item(q: Dict, cluster_id: str, cat2: str) -> Dict:
    return {
        "qd_id": q["id"],
        "cluster_id": cluster_id,
        "question": q["question"],
        "cat1": q.get("cat1", ""),
        "cat2": q.get("cat2", cat2),
        "tags": q.get("tags", ""),
        "diff_tag": q.get("diff_tag", ""),
        "url": q.get("url", ""),
        "company": q.get("company", ""),
        "round": q.get("round", ""),
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
        cid = (
            _extract_id(m.get("cluster_id", ""))
            if m.get("cluster_id") is not None
            else None
        )
        if not cid and m.get("target_id") is not None:
            cid = _extract_id(m.get("target_id", ""))
        if nid in unmatched_ids and nid not in processed_new_ids and cid is not None:
            processed_new_ids.add(nid)
            normalized = dict(m)
            normalized["new_id"] = nid
            normalized["cluster_id"] = cid
            raw_matches.append(normalized)
    return raw_matches


def _validate_direct_matches_enabled() -> bool:
    """高置信直通匹配是否也进二次验证（根因 #1：直通里有偏宽误合并）。

    默认关闭（保持现状行为与 LLM 成本）；验证层效果确认后可开启：
    CLUSTER_VALIDATE_DIRECT=1
    """
    return os.environ.get("CLUSTER_VALIDATE_DIRECT", "").strip().lower() in ("1", "true", "yes")


def _partition_matches_by_risk(
    matches: List[Dict], cat2: str
) -> tuple[List[Dict], List[Dict]]:
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


def _format_existing_clusters(clusters):
    """格式化已有聚类供 Prompt 使用（只传 ID + [标签] + 代表题，节省 Token）

    实验结论 P2：已有聚类的语义标签（cluster_label）帮助 LLM 快速定位
    考察点，标签缺失时回退为「[ID] 代表题」。
    """
    lines = []
    for c in clusters:
        label = c.get("cluster_label") if isinstance(c, dict) else None
        if label:
            lines.append(f"[{c['id']}] [{label}] {c['question']}")
        else:
            lines.append(f"[{c['id']}] {c['question']}")
    return "\n".join(lines)


async def _scan_async(func):
    """将同步 DB 操作包装为异步。"""
    return await asyncio.to_thread(func)


# ──────────────────────────── 验证 ────────────────────────────


async def _validate_merges(
    matches: List[Dict],
    new_questions: List[Dict],
    existing_clusters: List[Dict],
    user_id=None,
):
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
    new_q_map = {str(q["id"]): q for q in new_questions}
    cluster_map = {str(c["id"]): c for c in existing_clusters}

    # 构建验证对
    validation_items = []
    pair_lookup = {}
    for match in matches:
        new_id = _extract_id(match.get("new_id", ""))
        cluster_id = _extract_id(match.get("cluster_id", ""))

        new_q = new_q_map.get(new_id)
        cluster_q = cluster_map.get(cluster_id)

        if new_q and cluster_q:
            validation_items.append(
                {
                    "match": match,
                    "new_id": new_id,
                    "cluster_id": cluster_id,
                    "pair_text": f"题目A (ID={new_id}): {new_q['question']}\n题目B (ID={cluster_id}): {cluster_q['question']}",
                }
            )
            pair_lookup[(new_id, cluster_id)] = (new_q, cluster_q)

    if not validation_items:
        # 没有可验证的对时，拒绝所有匹配（而非放行）
        logger.warning(f"[验证] 无法构建验证对 ({len(matches)} 匹配被拒绝)")
        return ([], {})

    # Pre-sort by embedding similarity (descending) so high-confidence pairs
    # fill earlier chunks, making each chunk more likely to pass validation.
    try:
        from app.services.embedding_service import encode_texts

        new_texts = []
        cluster_texts = []
        valid_indices = []
        for idx, item in enumerate(validation_items):
            nq = new_q_map.get(item["new_id"])
            cq = cluster_map.get(item["cluster_id"])
            if nq and cq:
                new_texts.append(nq.get("question", ""))
                cluster_texts.append(cq.get("question", ""))
                valid_indices.append(idx)

        if new_texts:
            new_embs = encode_texts(new_texts)
            cluster_embs = encode_texts(cluster_texts)
            sims = np.einsum("ij,ij->i", new_embs, cluster_embs)

            scored = [
                (validation_items[valid_indices[i]], float(sims[i]))
                for i in range(len(sims))
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            validation_items = [item for item, _ in scored]
    except Exception as e:
        logger.debug(f"验证排序降级（使用原始顺序）: {e}")

    chunks = [
        validation_items[i : i + VALIDATION_BATCH_SIZE]
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
            semaphore = matcher_semaphore

            async def _guarded_validate(chunk):
                async with semaphore:
                    try:
                        result = await _validate_chunk(chunk)
                        matcher_semaphore.record_success()
                        return result
                    except Exception as e:
                        if "rate" in str(e).lower() or "429" in str(e):
                            matcher_semaphore.record_rate_limit_error()
                        logger.warning(
                            f"验证分块失败，拒绝该分块 {len(chunk)} 对合并: {e}"
                        )
                        return []

            chunk_results = await asyncio.gather(
                *[_guarded_validate(chunk) for chunk in chunks], return_exceptions=False
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
            new_id = _extract_id(match.get("new_id", ""))
            cluster_id = _extract_id(match.get("cluster_id", ""))

            # 查找对应的验证结果（用纯数字 ID 匹配，兼容 LLM 带前缀）
            validation = next(
                (
                    v
                    for v in validations
                    if _extract_id(v.get("new_id")) == new_id
                    and _extract_id(v.get("cluster_id")) == cluster_id
                ),
                None,
            )

            if validation:
                is_valid = validation.get("valid", False)
                confidence = float(validation.get("confidence", 0))
                reason = validation.get("reason", "")
                confidence_map[(new_id, cluster_id)] = confidence

                if is_valid and confidence >= VALIDATION_CONFIDENCE_THRESHOLD:
                    validated_matches.append(match)
                    logger.info(
                        f"  验证通过: 新题 {new_id} -> 聚类 {cluster_id} "
                        f"(置信度={confidence:.2f}, 原因={reason})"
                    )
                else:
                    # 记录拒绝原因
                    reject_reason = (
                        reason
                        if reason
                        else (
                            f"置信度不足 ({confidence:.2f} < {VALIDATION_CONFIDENCE_THRESHOLD})"
                            if is_valid
                            else "验证未通过"
                        )
                    )
                    logger.info(
                        f"  验证拒绝合并: 新题 {new_id} -> 聚类 {cluster_id} "
                        f"(置信度={confidence:.2f}, 原因={reject_reason})"
                    )
                    # 低置信度的有效判定 → 二次人工审核
                    if is_valid and confidence < VALIDATION_CONFIDENCE_THRESHOLD:
                        pair_data = pair_lookup.get((new_id, cluster_id))
                        rejected_for_review.append(
                            {
                                "new_id": new_id,
                                "cluster_id": cluster_id,
                                "new_question": pair_data[0]["question"]
                                if pair_data
                                else "",
                                "cluster_question": pair_data[1]["question"]
                                if pair_data
                                else "",
                                "confidence": confidence,
                                "reason": reason,
                            }
                        )
            else:
                logger.info(
                    f"  验证拒绝合并: 新题 {new_id} -> 聚类 {cluster_id} (无验证结果)"
                )

        if rejected_for_review:
            logger.warning(
                f"  ⚠ {len(rejected_for_review)} 对合并需要二次人工审核 "
                f"(置信度 < {VALIDATION_CONFIDENCE_THRESHOLD}): "
                + ", ".join(
                    f"新题{r['new_id']}→聚类{r['cluster_id']}(c={r['confidence']:.2f})"
                    for r in rejected_for_review
                )
            )

        return (validated_matches, confidence_map)

    except Exception as e:
        logger.warning(f"验证合并失败，拒绝所有合并: {e}")
        return ([], {})  # 验证失败时拒绝所有合并，而非返回原始匹配


# ──────────────────────────── 最近题目加载 ────────────────────────────


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
            (cat2, f"-{days} days"),
        ).fetchall()
        return [{"id": r["id"], "question": r["question"]} for r in rows]

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
            (cat2,),
        ).fetchone()
        return row["cnt"] if row else 0

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


# ──────────────────────────── 内部匹配逻辑 ────────────────────────────


async def _match_and_cluster_cat2(
    cat2, new_questions, existing_clusters, user_id, recent_days=RECENT_DAYS
):
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
    unmatched_ids = {str(q["id"]) for q in new_questions}

    filtered_clusters = existing_clusters
    if existing_clusters:
        try:
            if len(existing_clusters) > _PREFILTER_TOP_K:
                batch_results = prefilter_centroids_batch(
                    query_texts=[q["question"] for q in new_questions],
                    centroids=existing_clusters,
                    top_k=_PREFILTER_TOP_K,
                )
                candidate_ids = set()
                for qi_results in batch_results.values():
                    candidate_ids.update(c["id"] for c in qi_results)
                filtered_clusters = [
                    c for c in existing_clusters if c["id"] in candidate_ids
                ]
                logger.info(
                    f"  [{cat2 or '无分类'}] Embedding 预筛选: {len(existing_clusters)} → {len(filtered_clusters)} 个候选 centroid"
                )
        except Exception as e:
            logger.warning(
                f"  [{cat2 or '无分类'}] Embedding 预筛选失败，降级为全量候选: {e}"
            )
            filtered_clusters = existing_clusters

    recent_singletons = []
    effective_days = recent_days
    if recent_days > 0:
        effective_days = (
            await calculate_dynamic_recent_days(cat2)
            if recent_days == RECENT_DAYS
            else recent_days
        )
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

    unmatched_questions = [q for q in new_questions if str(q["id"]) in unmatched_ids]
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
            direct_matches, matches_to_validate = _partition_matches_by_risk(
                raw_matches, cat2
            )

            # 根因 #1：高置信直通也进二次验证（可选，CLUSTER_VALIDATE_DIRECT=1）
            if _validate_direct_matches_enabled() and direct_matches:
                matches_to_validate = list(direct_matches) + list(matches_to_validate)
                direct_matches = []

            if matches_to_validate:
                logger.info(
                    f"  [{cat2 or '无分类'}] 中置信/保守匹配需二次验证: {len(matches_to_validate)} 题"
                )
                validated_matches, _confidence_map = await _validate_merges(
                    matches_to_validate, unmatched_questions, candidate_pool, user_id
                )
            else:
                validated_matches = []

            accepted_matches = list(direct_matches) + list(validated_matches)
            accepted_ids = set()
            q_by_id = {str(q["id"]): q for q in unmatched_questions}
            for m in accepted_matches:
                nid = _extract_id(m.get("new_id", ""))
                cid = (
                    _extract_id(m.get("cluster_id", ""))
                    if m.get("cluster_id") is not None
                    else None
                )
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
    unmatched_questions = [q for q in new_questions if str(q["id"]) in unmatched_ids]
    new_clusters = await _cluster_unmatched(unmatched_questions, user_id)

    return {"matched": matched, "new_clusters": new_clusters}


# ──────────────────────────── 公开入口 ────────────────────────────


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
        cat2 = r.get("cat2") or ""
        if cat2:
            cat2_groups.setdefault(cat2, []).append(r)
        else:
            no_cat2.append(r)

    if no_cat2:
        cat2_groups[""] = no_cat2

    cat2_list = list(cat2_groups.items())
    semaphore = matcher_semaphore

    async def _process_one(cat2, questions):
        async with semaphore:
            try:
                existing = existing_by_cat2.get(cat2, [])
                result = await _match_and_cluster_cat2(
                    cat2, questions, existing, user_id, recent_days=recent_days
                )
                matcher_semaphore.record_success()
                return result
            except Exception as e:
                if "rate" in str(e).lower() or "429" in str(e):
                    matcher_semaphore.record_rate_limit_error()
                raise

    tasks = [_process_one(cat2, questions) for cat2, questions in cat2_list]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_matched = []
    all_new_clusters = []
    for (cat2, _), res in zip(cat2_list, results):
        if isinstance(res, Exception):
            logger.error(f"[{cat2 or '无分类'}] cat2 处理异常: {res}")
        else:
            all_matched.extend(res["matched"])
            all_new_clusters.extend(res["new_clusters"])

    return {
        "matched_to_existing": all_matched,
        "new_clusters": all_new_clusters,
    }


# ──────────────────────────── 保留的工具函数 ────────────────────────────


async def generate_unified_question(
    questions: list[str], sources_context: list[dict] | None = None, user_id=None
) -> str:
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
        cat2 = r.get("cat2") or ""
        cat2_groups.setdefault(cat2, []).append(r)

    semaphore = matcher_semaphore

    async def _match_group(cat2, group):
        existing = existing_clusters_by_cat2.get(cat2, [])
        if not existing:
            return [], group

        # 构建 cluster_id → question_bank_id 映射（兼容两种格式）
        id_to_qb = {}
        normalized = []
        for c in existing:
            cid = c.get("id") or c.get("question_bank_id")
            id_to_qb[cid] = cid
            normalized.append({**c, "id": cid})

        async with semaphore:
            prompt = MATCH_EXISTING_PROMPT.format(
                existing_clusters=_format_existing_clusters(normalized),
                new_questions=_format_new_questions(group),
                count=len(group),
            )
            content = await _call_llm_with_retry(
                prompt, response_format={"type": "json_object"}, user_id=user_id
            )

        result = _extract_json(content)
        group_matched = []
        group_unmatched = []
        group_matched_ids = set()

        # 同一新题被 LLM 匹配到多个聚类时只保留第一个（bug 回归：
        # mock 增量评估实测一道题返回 3 个 cluster 匹配，个人路径无去重；
        # 与生产 _match_and_cluster_cat2 的 accepted_ids 语义保持一致）
        for m in result.get("matches", []):
            new_id = _extract_id(m.get("new_id"))
            cluster_id = _extract_id(m.get("cluster_id"))
            try:
                cluster_id_int = int(cluster_id) if cluster_id else None
                new_id_int = int(new_id) if new_id else None
            except (ValueError, TypeError):
                continue
            if (
                new_id_int is not None
                and cluster_id_int is not None
                and cluster_id_int in id_to_qb
                and new_id_int not in group_matched_ids
            ):
                group_matched.append(
                    {"new_id": new_id_int, "question_bank_id": id_to_qb[cluster_id_int]}
                )
                group_matched_ids.add(new_id_int)
        for r in group:
            if r["id"] not in group_matched_ids:
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

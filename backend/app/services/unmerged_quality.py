"""漏合并质量审查：复用孤岛复核逻辑，生成管理员待审批清单。

本模块只做候选发现和 `quality_issue(status='pending')` 写入，不直接修改题库。
真正的合并必须经过管理员审批，由 `quality_issue_ops` 调用现有合并实现完成。
"""

import json
import logging
import re

from app.db.connection import get_db_connection
from app.db.quality_issue_identity import (
    build_issue_fingerprint,
    upsert_quality_issue,
)
from app.services.llm import _call_llm_with_retry
from app.services.clustering.experiments.memory_labels import generate_cluster_labels

logger = logging.getLogger("interview-boss")

ISLAND_SIM_THRESHOLD = 0.30
ISLAND_TOP_CANDIDATES = 3
UNMERGED_CONFIDENCE_FLOOR = 0.50

ISLAND_REVIEW_PROMPT = """你是面试题去重专家。下面有两道面试题，请判断它们**是否应该视为同一道面试题**（合并到同一个聚类）。

合并标准：表述不同但考察点完全相同（如"怎样做限流" vs "限流方案有哪些"）。
不合并标准：
- 考察点不同的（如"TCP 三次握手" vs "IO 多路复用"、"缓存使用场景" vs "缓存穿透击穿怎么解决"）
- 主题相近但问题不同的（如"Redis 数据结构有哪些" vs "Redis 为什么快"）
- 具体算法题 vs 口述思路（如"合并两个有序链表" vs "口述算法题的解题思路"）

【题目 A：当前孤岛题】
{question_a}

【题目 B：已有聚类代表题】
{label} | {question_b}

输出格式（严格 JSON，不要输出其他内容）：
{{"same": true 或 false, "confidence": 0.0 到 1.0 的小数, "reason": "一句话原因"}}"""


def jaccard_sim(a: str, b: str) -> float:
    """字符级 Jaccard 相似度，用于免费候选预筛，不作为合并决定。"""
    set_a, set_b = set(a or ""), set(b or "")
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def find_candidates(
    singleton_q: str,
    labels: dict[int, str],
    threshold: float = ISLAND_SIM_THRESHOLD,
    top_n: int = ISLAND_TOP_CANDIDATES,
) -> list[tuple[int, str, float]]:
    """按字符级相似度为孤岛题找 top-N 聚类标签候选。"""
    scored = []
    for qid, label in labels.items():
        sim = jaccard_sim(singleton_q, label)
        if sim >= threshold:
            scored.append((qid, label, sim))
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored[:top_n]


def _extract_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _load_public_cluster_data(conn, limit: int) -> tuple[list[dict], list[dict]]:
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, frequency, original_questions "
        "FROM question_bank WHERE deleted_at IS NULL AND owner_id IS NULL "
        "AND status = 'approved' ORDER BY id"
    ).fetchall()
    clusters, singletons = [], []
    for row in rows:
        try:
            originals = json.loads(row["original_questions"] or "[]")
        except (TypeError, json.JSONDecodeError):
            originals = []
        if not isinstance(originals, list):
            originals = []
        originals = [str(q).strip() for q in originals if str(q).strip()]
        item = {
            "qb_id": row["id"],
            "question": row["question"] or "",
            "cat1": row["cat1"] or "",
            "cat2": row["cat2"] or "",
            "freq": row["frequency"] or 1,
            "oq": originals,
        }
        if item["freq"] > 1:
            clusters.append(item)
        elif len(singletons) < limit:
            singletons.append(item)
    return clusters, singletons


def _issue_exists(
    conn,
    source_id: int,
    target_id: int,
    source_question: str,
    review_version: str | None = None,
) -> bool:
    fingerprint = build_issue_fingerprint("unmerged", source_question)
    row = conn.execute(
        "SELECT 1 FROM quality_issue WHERE issue_fingerprint = ? LIMIT 1",
        (fingerprint,),
    ).fetchone()
    if row:
        return True

    # Compatibility fallback for rows created before migration 077 (or by a
    # lightweight external importer that has not populated the fingerprint).
    if review_version:
        row = conn.execute(
            "SELECT 1 FROM quality_issue WHERE qb_id = ? AND review_version = ? "
            "AND issue_type = 'unmerged' AND suggested_action = 'merge' "
            "AND target_qb_id = ? AND variant_key = ? LIMIT 1",
            (source_id, review_version, target_id, f"target:{target_id}"),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM quality_issue WHERE qb_id = ? AND variant_index IS NULL "
            "AND issue_type = 'unmerged' AND suggested_action = 'merge' "
            "AND target_qb_id = ? AND status IN ('pending', 'approved') LIMIT 1",
            (source_id, target_id),
        ).fetchone()
    return row is not None


async def generate_unmerged_quality_issues(
    user_id: int | None = None,
    limit: int = 200,
    candidate_limit: int = ISLAND_TOP_CANDIDATES,
    similarity_threshold: float = ISLAND_SIM_THRESHOLD,
    review_task_id: str | None = None,
    trigger_reason: str = "manual_unmerged_scan",
) -> dict:
    """把 LLM 判定应合并的孤岛题写入管理员 pending 清单。

    流程与 `clustering/experiments/review_islands.py` 一致：
    1. 公共 frequency=1 孤岛题；
    2. 字符 Jaccard 预筛已有聚类标签；
    3. LLM 逐对复核；
    4. 仅落库清单，不执行合并。
    """
    limit = max(1, min(int(limit), 1000))
    candidate_limit = max(1, min(int(candidate_limit), 10))
    similarity_threshold = max(0.0, min(float(similarity_threshold), 1.0))

    with get_db_connection() as conn:
        clusters, singletons = _load_public_cluster_data(conn, limit)

    if not clusters or not singletons:
        return {
            "created": 0,
            "singletons": len(singletons),
            "clusters": len(clusters),
            "candidate_pairs": 0,
            "reviewed_pairs": 0,
            "scanned_singleton_ids": [s["qb_id"] for s in singletons],
        }

    # 直接复用现有实验代码的聚类标签生成逻辑；失败时该逻辑会回退代表题。
    labels = await generate_cluster_labels(clusters, user_id=user_id)
    candidates = []
    for singleton in singletons:
        for target_id, label, sim in find_candidates(
            singleton["question"],
            labels,
            threshold=similarity_threshold,
            top_n=candidate_limit,
        ):
            if target_id == singleton["qb_id"]:
                continue
            target = next((c for c in clusters if c["qb_id"] == target_id), None)
            if target:
                candidates.append((singleton, target, label, sim))

    created = reviewed = 0
    for singleton, target, label, sim in candidates:
        prompt = ISLAND_REVIEW_PROMPT.format(
            question_a=singleton["question"],
            label=label,
            question_b=target["question"],
        )
        try:
            raw = await _call_llm_with_retry(
                prompt,
                system_msg="你是一个面试题去重专家。",
                response_format=None,
                user_id=user_id,
                model=None,
            )
            data = _extract_json_object(raw)
        except Exception as exc:
            logger.warning(
                "[漏合并清单] LLM 复核失败 source=%s target=%s: %s",
                singleton["qb_id"],
                target["qb_id"],
                exc,
            )
            continue

        reviewed += 1
        if not bool(data.get("same")):
            continue
        try:
            confidence = float(data.get("confidence", 0.85))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(confidence, 1.0))
        if confidence < UNMERGED_CONFIDENCE_FLOOR:
            continue

        reason = str(data.get("reason") or "判定为同一道面试题")[:300]
        reason = f"漏合并复核（预筛相似度 {sim:.2f}）：{reason}"
        with get_db_connection() as conn:
            from app.services.cluster_review_lifecycle import get_current_cluster_version

            review_version = get_current_cluster_version(conn, singleton["qb_id"])
            if not review_version:
                continue
            if _issue_exists(
                conn,
                singleton["qb_id"],
                target["qb_id"],
                singleton["question"],
                review_version,
            ):
                continue
            _, inserted = upsert_quality_issue(conn, {
                "qb_id": singleton["qb_id"],
                "variant_index": None,
                "issue_type": "unmerged",
                "suggested_action": "merge",
                "reason": reason,
                "suggested_value": None,
                "confidence": round(confidence, 2),
                "status": "pending",
                "target_qb_id": target["qb_id"],
                "new_cat2": None,
                "source_question": singleton["question"],
                "source_cat2": singleton["cat2"],
                "review_version": review_version,
                "review_task_id": review_task_id,
                "trigger_reason": trigger_reason,
                "variant_key": f"target:{target['qb_id']}",
                "issue_fingerprint": build_issue_fingerprint(
                    "unmerged", singleton["question"]
                ),
            })
            conn.commit()
        created += int(inserted)

    logger.info(
        "[漏合并清单] 完成: 孤岛=%d 聚类=%d 候选=%d 复核=%d 新增=%d",
        len(singletons),
        len(clusters),
        len(candidates),
        reviewed,
        created,
    )
    return {
        "created": created,
        "singletons": len(singletons),
        "clusters": len(clusters),
        "candidate_pairs": len(candidates),
        "reviewed_pairs": reviewed,
        "scanned_singleton_ids": [s["qb_id"] for s in singletons],
    }


def merge_question(
    conn,
    source_qb_id: int,
    target_qb_id: int,
    confidence: float = 0.0,
    operator_id: int | None = None,
) -> bool:
    """审批漏合并清单时，将整道来源题并入目标题。

    复用现有 `_do_merge_to_existing`，因此来源/原始问法/规范化来源表及
    `merge_history` 与正常聚类合并保持同一口径。
    """
    if source_qb_id == target_qb_id:
        return False
    source = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, sources, "
        "original_questions, original_question_sources, ai_answer, answer_sources "
        "FROM question_bank WHERE id = ? AND deleted_at IS NULL AND owner_id IS NULL "
        "AND status = 'approved'",
        (source_qb_id,),
    ).fetchone()
    target = conn.execute(
        "SELECT id, cat2 FROM question_bank "
        "WHERE id = ? AND deleted_at IS NULL AND owner_id IS NULL AND status = 'approved'",
        (target_qb_id,),
    ).fetchone()
    if not source or not target:
        return False

    from app.services.pipeline.compact import _do_merge_to_existing

    _do_merge_to_existing(
        target_qb_id,
        dict(source),
        operation_type="manual",
        phase="quality_issue_unmerged",
        cat2=target["cat2"] or "",
        operator_id=operator_id,
        confidence=confidence,
    )
    return True

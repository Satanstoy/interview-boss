"""Clustering maintenance and deterministic data repair.

This module keeps admin routes thin and centralizes safe repairs for
question_bank clustering metadata. It deliberately avoids using embedding
thresholds as merge decisions.
"""

import asyncio
import json
import logging
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from app.db.question_bank_sources import (
    delete_all_for_qb,
    insert_original_item,
    insert_source,
)
from app.db.quality_issue_identity import (
    build_issue_fingerprint,
    upsert_quality_issue,
)

logger = logging.getLogger("interview-boss")


def normalize_question_text(text: str) -> str:
    """Normalize text for exact duplicate detection, not semantic matching."""
    text = (text or "").lower().strip()
    return re.sub(r"[\s，。！？?；;：:、,.()（）\[\]【】\"“”‘’\-_/\n\r\t]+", "", text)


def _json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _sync_question_cluster_normalized_tables(conn, qb_id: int) -> None:
    """Keep normalized question tables aligned after a review mutation.

    Review operations update the JSON columns on ``question_bank`` directly.
    The normalized tables are part of the same read model, so every mutation
    path must refresh them before the enclosing approval transaction commits.
    """
    from app.services.question_variant_reconciliation import _sync_normalized_tables

    _sync_normalized_tables(conn, qb_id)


def _append_unique(items: list, value: str) -> bool:
    value = (value or "").strip()
    if not value or value in items:
        return False
    items.append(value)
    return True


def _merge_sources(existing: list, incoming: list) -> list:
    merged = [s for s in existing if isinstance(s, dict)]
    seen = {
        (s.get("url", ""), s.get("company", ""), s.get("round", "")) for s in merged
    }
    for src in incoming:
        if not isinstance(src, dict):
            continue
        key = (src.get("url", ""), src.get("company", ""), src.get("round", ""))
        if key not in seen:
            merged.append(src)
            seen.add(key)
    return merged


def _ensure_original_source(original_sources: list, question: str, sources: list):
    question = (question or "").strip()
    if not question:
        return
    for item in original_sources:
        if item.get("question") == question:
            item["sources"] = _merge_sources(item.get("sources", []), sources)
            return
    original_sources.append({"question": question, "sources": list(sources or [])})


def _canonical_cluster_payload(row: Dict) -> Tuple[List[str], List[Dict]]:
    sources = _json_list(row.get("sources"))
    originals: List[str] = []
    for q in _json_list(row.get("original_questions")):
        _append_unique(originals, q)

    original_sources = []
    for item in _json_list(row.get("original_question_sources")):
        if not isinstance(item, dict):
            continue
        q = item.get("question", "")
        if _append_unique(originals, q):
            pass
        _ensure_original_source(original_sources, q, item.get("sources", []))

    if not originals:
        _append_unique(originals, row.get("question", ""))

    for q in originals:
        _ensure_original_source(
            original_sources,
            q,
            sources if q == (row.get("question") or "").strip() else [],
        )
    return originals, original_sources


def _history_merged_questions(conn, survivor_id: int) -> List[str]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_history'"
    ).fetchone()
    if not exists:
        return []
    rows = conn.execute(
        "SELECT merged_questions FROM merge_history WHERE survivor_id = ? ORDER BY id",
        (survivor_id,),
    ).fetchall()
    questions = []
    for row in rows:
        for q in _json_list(row["merged_questions"]):
            _append_unique(questions, q)
    return questions


def _sync_normalized_tables(conn, qb_id: int, sources: list, original_sources: list):
    delete_all_for_qb(conn, qb_id)
    for src in sources:
        if not isinstance(src, dict):
            continue
        insert_source(
            conn,
            qb_id,
            src.get("url", ""),
            src.get("company", ""),
            src.get("round", ""),
        )
    for item in original_sources:
        if not isinstance(item, dict):
            continue
        insert_original_item(
            conn, qb_id, item.get("question", ""), item.get("sources", [])
        )


def audit_clustering_state(conn) -> Dict:
    rows = conn.execute(
        "SELECT id, question, cat2, frequency, cluster_id, sources, "
        "original_questions, original_question_sources "
        "FROM question_bank WHERE deleted_at IS NULL"
    ).fetchall()
    rows = [dict(r) for r in rows]

    exact_groups = defaultdict(list)
    for row in rows:
        norm = normalize_question_text(row["question"])
        if norm:
            exact_groups[norm].append(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "cat2": row.get("cat2") or "",
                    "frequency": row.get("frequency") or 0,
                }
            )

    exact_duplicate_groups = [
        {"normalized": key, "items": items}
        for key, items in exact_groups.items()
        if len(items) > 1
    ]

    normalized_counts = {
        "question_sources": conn.execute(
            "SELECT COUNT(*) FROM question_sources"
        ).fetchone()[0],
        "question_original_items": conn.execute(
            "SELECT COUNT(*) FROM question_original_items"
        ).fetchone()[0],
        "question_original_item_sources": conn.execute(
            "SELECT COUNT(*) FROM question_original_item_sources"
        ).fetchone()[0],
    }

    freq_mismatch = []
    normalized_mismatch = []
    for row in rows:
        originals, _ = _canonical_cluster_payload(row)
        expected = max(1, len(originals))
        if (row.get("frequency") or 0) != expected:
            freq_mismatch.append(
                {
                    "id": row["id"],
                    "frequency": row.get("frequency") or 0,
                    "expected": expected,
                    "question": row["question"],
                }
            )
        qoi_count = conn.execute(
            "SELECT COUNT(*) FROM question_original_items WHERE question_bank_id = ?",
            (row["id"],),
        ).fetchone()[0]
        if qoi_count != len(originals):
            normalized_mismatch.append(
                {
                    "id": row["id"],
                    "normalized_original_count": qoi_count,
                    "expected": len(originals),
                }
            )

    return {
        "total_active": len(rows),
        "frequency_zero": [r["id"] for r in rows if (r.get("frequency") or 0) == 0],
        "null_cluster_id": [r["id"] for r in rows if r.get("cluster_id") is None],
        "frequency_mismatch": freq_mismatch,
        "normalized_mismatch": normalized_mismatch,
        "exact_duplicate_groups": exact_duplicate_groups,
        "normalized_counts": normalized_counts,
    }


def _repair_row_metadata(conn, row: Dict) -> Dict:
    sources = _json_list(row.get("sources"))
    originals, original_sources = _canonical_cluster_payload(row)
    for q in _history_merged_questions(conn, row["id"]):
        if _append_unique(originals, q):
            _ensure_original_source(original_sources, q, [])

    frequency = max(1, len(originals))
    conn.execute(
        "UPDATE question_bank SET frequency = ?, cluster_id = COALESCE(cluster_id, id), "
        "original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (
            frequency,
            json.dumps(originals, ensure_ascii=False),
            json.dumps(original_sources, ensure_ascii=False),
            row["id"],
        ),
    )
    _sync_normalized_tables(conn, row["id"], sources, original_sources)
    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

    mark_cluster_review_pending(conn, row["id"], "metadata_repaired")
    return {"id": row["id"], "frequency": frequency, "original_count": len(originals)}


def _merge_exact_duplicate_pair(conn, survivor_id: int, merged_id: int) -> Dict:
    from app.services.pipeline.compact import _do_merge_to_existing

    row = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, sources, "
        "original_questions, original_question_sources, ai_answer, answer_sources "
        "FROM question_bank WHERE id = ? AND deleted_at IS NULL",
        (merged_id,),
    ).fetchone()
    if not row:
        return {}
    _do_merge_to_existing(
        survivor_id,
        dict(row),
        operation_type="maintenance",
        phase="exact_duplicate",
        cat2=row["cat2"] or "",
        confidence=0.95,
    )
    return {
        "survivor_id": survivor_id,
        "merged_id": merged_id,
        "question": row["question"],
    }


def run_clustering_maintenance(
    conn, execute: bool = False, merge_exact_duplicates: bool = True
) -> Dict:
    """Audit clustering data and optionally apply deterministic repairs."""
    before = audit_clustering_state(conn)
    if not execute:
        return {
            "dry_run": True,
            "audit": before,
            "applied": {"metadata": [], "exact_merges": []},
        }

    applied = {"metadata": [], "exact_merges": []}
    rows = conn.execute(
        "SELECT id, question, cat2, frequency, cluster_id, sources, "
        "original_questions, original_question_sources "
        "FROM question_bank WHERE deleted_at IS NULL"
    ).fetchall()

    conn.execute("BEGIN")
    try:
        for row in rows:
            applied["metadata"].append(_repair_row_metadata(conn, dict(row)))

        if merge_exact_duplicates:
            audit_after_metadata = audit_clustering_state(conn)
            for group in audit_after_metadata["exact_duplicate_groups"]:
                items = sorted(
                    group["items"], key=lambda x: (-(x["frequency"] or 0), x["id"])
                )
                survivor = items[0]
                for item in items[1:]:
                    result = _merge_exact_duplicate_pair(
                        conn, survivor["id"], item["id"]
                    )
                    if result:
                        applied["exact_merges"].append(result)

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    after = audit_clustering_state(conn)
    logger.info(
        "[聚类维护] execute=%s metadata=%s exact_merges=%s",
        execute,
        len(applied["metadata"]),
        len(applied["exact_merges"]),
    )
    return {"dry_run": False, "audit": before, "applied": applied, "after": after}


# ── 聚类语义标签生成（实验结论 P2）──

CLUSTER_LABEL_PROMPT = """你是面试题题库管理专家。下面是一个【已有题目聚类】的代表题与原始题面变体，请为该聚类生成一个**规范标签**（一句话概括规范题面，20 字以内，作为该聚类的"记忆标签"）。

只输出 JSON 对象：{{"label": "..."}}"""


async def generate_missing_cluster_labels(
    user_id: int = None, batch_size: int = 20
) -> dict:
    """为缺少 cluster_label 的已有聚类（frequency > 1 的代表题）分批生成语义标签。

    幂等：只处理 cluster_label IS NULL 的代表题；失败回退保持 NULL（下次再补）。
    Returns: {"generated": int, "skipped": int, "failed": int}
    """
    from app.db.connection import get_db_connection
    from app.services.llm import _call_llm_with_retry

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, question, original_questions FROM question_bank "
            "WHERE deleted_at IS NULL AND frequency > 1 AND cluster_label IS NULL "
            "ORDER BY id"
        ).fetchall()
    if not rows:
        return {"generated": 0, "skipped": 0, "failed": 0}

    generated = failed = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        for r in batch:
            try:
                import json

                oq = []
                try:
                    oq = json.loads(r["original_questions"] or "[]")[:6]
                except Exception:
                    oq = []
                variants = " | ".join(str(q) for q in oq if str(q).strip())
                prompt = (
                    f"【聚类代表题】\n{r['question']}\n\n"
                    f"【原始题面变体】\n{variants or '（无）'}\n\n"
                    + CLUSTER_LABEL_PROMPT
                )
                raw = await _call_llm_with_retry(
                    prompt,
                    system_msg="你是一个面试题题库管理专家。",
                    response_format=None,
                    user_id=user_id,
                    model=None,
                )
                label = _extract_label_from_json(raw)
                if not label:
                    failed += 1
                    continue
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE question_bank SET cluster_label = ? WHERE id = ?",
                        (label, r["id"]),
                    )
                generated += 1
            except Exception as e:
                logger.warning(f"[聚类标签] 生成失败 qb_id={r['id']}: {e}")
                failed += 1
    logger.info("[聚类标签] 完成: generated=%d failed=%d", generated, failed)
    return {"generated": generated, "skipped": 0, "failed": failed}


def _extract_label_from_json(raw: str) -> str:
    """从 LLM 输出提取 label（容忍 markdown/前后文字/对象包裹）"""
    from app.services.llm_judge import parse_json_object

    data = parse_json_object(raw)
    if data:
        label = data.get("label")
        return str(label).strip() if label else ""
    return ""


# ── 变体归一化（根因 #2）：LLM 语义判重，清洗重复变体 ──

VARIANT_DUPLICATE_PROMPT = """你是面试题去重专家。以下是同一聚类下的【原始题面变体】列表。

请找出**语义重复**的变体对（同一道面试题的不同表述，如"介绍rag流程"与"讲述一下rag的流程"）。
注意：仅表述不同但考察点相同的算重复；考察点不同的不算（那是误合并，不属于本任务）。

{items}

输出格式（严格 JSON）：{{"duplicates": [[0, 1], [2, 0]]}}
其中每对 [i, j] 表示变体 i 与变体 j 重复，保留编号小者（编号大者将被合并掉）。"""


async def _llm_find_duplicate_variants(variants: list[str], user_id: int = None) -> list[list[int]]:
    """LLM 语义判重：返回重复变体对 [[keep_idx, merge_idx], ...]（keep 保留较小下标）。

    失败返回 []（不动数据，等待下次清洗）。
    """
    if len(variants) < 2:
        return []
    items = "\n".join(f"{i}. {v}" for i, v in enumerate(variants))
    prompt = VARIANT_DUPLICATE_PROMPT.format(items=items)
    try:
        from app.services.llm import _call_llm_with_retry
        from app.services.llm_judge import parse_json_object

        raw = await _call_llm_with_retry(
            prompt, system_msg="你是一个面试题去重专家。",
            response_format=None, user_id=user_id, model=None,
        )
        data = parse_json_object(raw)
        pairs = data.get("duplicates", []) if data else []
        out = []
        for p in pairs:
            if not isinstance(p, list) or len(p) != 2:
                continue
            try:
                i, j = int(p[0]), int(p[1])
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(variants) and 0 <= j < len(variants) and i != j:
                out.append(sorted([i, j]))
        return out
    except Exception as e:
        logger.warning(f"[变体归一] LLM 判重失败: {e}")
        return []


def _merge_variant_duplicates(oq: list[str], dup_pairs: list[list[int]]) -> list[str]:
    """按判重对合并变体：每对保留较小下标者，返回去重后的 oq（保持原顺序）。"""
    if not dup_pairs:
        return oq
    merge_targets = set()
    for pair in dup_pairs:
        drop = max(pair)  # 保留较小下标
        merge_targets.add(drop)
    return [v for idx, v in enumerate(oq) if idx not in merge_targets]


# ── 聚类质量定期审查（根因三问题解决后的质量监控）──

AUDIT_SAMPLE_SIZE = 20
AUDIT_INCONSISTENT_THRESHOLD = 0.10  # 误合并率 > 10% → 触发清洗提示

AUDIT_EVAL_PROMPT = """你是面试题去重专家。以下是同一聚类下的【代表题】与【原始题面变体】。

请评估：
1. 每个变体与代表题考察点是否一致（consistent=true 一致 / false 误合并）
2. 代表题是否涵盖所有一致变体（representative_covers_all）
3. 变体间是否重复（duplicates: 重复变体 index 数组）

【代表题】
{representative}

【变体列表】
{variants}

输出格式（严格 JSON）：
{{"variants": [{{"index": 0, "consistent": true, "reason": "一句话"}}],
  "representative_covers_all": true,
  "duplicates": [0, 2]}}"""


async def run_quality_audit(user_id: int = None, sample_size: int = AUDIT_SAMPLE_SIZE) -> dict:
    """公共题库聚类质量抽查：抽样核验变体一致性，写 quality_audit 表。

    误合并率 > AUDIT_INCONSISTENT_THRESHOLD → triggered_cleanup=1（提示清洗）。
    Returns: 指标 dict
    """
    import os
    import time as _time

    from app.db.connection import get_db_connection
    from app.services.llm import _call_llm_with_retry
    from app.services.llm_judge import parse_json_object

    report_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "experiment_reports"
    ))
    os.makedirs(report_dir, exist_ok=True)

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, question, frequency, original_questions FROM question_bank "
            "WHERE deleted_at IS NULL AND owner_id IS NULL AND frequency > 1 "
            "ORDER BY frequency DESC LIMIT ?",
            (sample_size,),
        ).fetchall()
    sample = []
    for r in rows:
        try:
            oq = json.loads(r["original_questions"] or "[]")
        except Exception:
            oq = []
        oq = [str(q).strip() for q in oq if str(q).strip()]
        if oq:
            sample.append({"id": r["id"], "question": r["question"], "oq": oq})

    total_variants = inconsistent = duplicates = coverage = 0
    lines = ["# 聚类质量定期审查报告", "",
             f"**时间**: {_time.strftime('%Y-%m-%d %H:%M:%S')}", "",
             f"- 抽样: {len(sample)} 个聚类", ""]

    for rep in sample:
        variants_text = "\n".join(f"{i}. {v}" for i, v in enumerate(rep["oq"]))
        prompt = AUDIT_EVAL_PROMPT.format(representative=rep["question"], variants=variants_text)
        try:
            raw = await _call_llm_with_retry(
                prompt, system_msg="你是一个面试题去重专家。",
                response_format=None, user_id=user_id, model=None,
            )
            data = parse_json_object(raw) or {}
        except Exception as e:
            logger.warning(f"[质量审查] 聚类 {rep['id']} 核验失败: {e}")
            continue
        v_map = {v.get("index"): v for v in data.get("variants", []) if isinstance(v, dict)}
        n = len(rep["oq"])
        total_variants += n
        bad = sum(1 for i in range(n) if not v_map.get(i, {}).get("consistent", True))
        inconsistent += bad
        duplicates += len(set(data.get("duplicates", []) or []))
        if data.get("representative_covers_all"):
            coverage += 1
        lines.append(
            f"- 聚类 {rep['id']}: {n} 变体 | 不一致 {bad} | "
            f"重复 {len(set(data.get('duplicates', []) or []))} | "
            f"涵盖 {'✅' if data.get('representative_covers_all') else '❌'}"
        )

    n_clusters = len(sample)
    inconsistent_rate = inconsistent / max(total_variants, 1)
    duplicate_rate = duplicates / max(total_variants, 1)
    coverage_rate = coverage / max(n_clusters, 1)
    triggered = int(inconsistent_rate > AUDIT_INCONSISTENT_THRESHOLD)

    report_path = os.path.join(report_dir, f"quality_audit_{_time.strftime('%Y%m%d_%H%M%S')}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n"
                f"## 指标\n\n- 误合并率: {inconsistent_rate * 100:.1f}%"
                f"（阈值 {AUDIT_INCONSISTENT_THRESHOLD * 100:.0f}%）\n"
                f"- 重复率: {duplicate_rate * 100:.1f}%\n"
                f"- 涵盖率: {coverage_rate * 100:.0f}%\n"
                f"- 触发清洗: {'✅' if triggered else '否'}\n")

    def _save():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO quality_audit (audited_at, sample_size, total_variants, "
                "inconsistent_count, duplicate_count, coverage_count, "
                "inconsistent_rate, duplicate_rate, coverage_rate, report_path, triggered_cleanup) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_time.strftime('%Y-%m-%d %H:%M:%S'), n_clusters, total_variants,
                 inconsistent, duplicates, coverage,
                 round(inconsistent_rate, 4), round(duplicate_rate, 4),
                 round(coverage_rate, 4), report_path, triggered),
            )
            conn.commit()

    try:
        await asyncio.to_thread(_save)
    except Exception as e:
        logger.warning(f"[质量审查] 落库失败: {e}")

    logger.info(
        "[质量审查] 抽样 %d 聚类: 误合并率 %.1f%% 重复率 %.1f%% 涵盖率 %.0f%% 触发清洗=%s",
        n_clusters, inconsistent_rate * 100, duplicate_rate * 100,
        coverage_rate * 100, triggered,
    )
    return {
        "sample_size": n_clusters, "total_variants": total_variants,
        "inconsistent_rate": round(inconsistent_rate, 4),
        "duplicate_rate": round(duplicate_rate, 4),
        "coverage_rate": round(coverage_rate, 4),
        "triggered_cleanup": triggered, "report_path": report_path,
    }


# ── 审查清单操作（管理员审批后执行）──

def split_variant(
    conn, qb_id: int, variant_index: int,
    new_representative: str | None = None, new_cat2: str | None = None,
) -> int | None:
    """拆出误合并变体：从代表题 oq 移除该变体 + frequency-1，拆出的变体独立入库。

    拆出的问法脱离访谈上下文可能不自明（如「关于研究生方向…」）。若传入
    new_representative（清单生成时 LLM 预生成的重写题面），用它作为新题代表题，
    原问法降为新题的 original_questions（保真，可追溯）；未传入则用原问法原文。

    new_cat2（LLM 重写的分类判定）：拆出的问法可能属于别的 cat2（误合并常因跨领域），
    不应硬继承原题分类；传入则用新分类，未传入回退原题 cat2。

    执行前重检（业界实践：审批后执行前再查当前状态）：oq 中不存在该下标 → None。
    Returns: 新题 id / None
    """
    row = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, job_position, owner_id, "
        "original_questions, sources "
        "FROM question_bank WHERE id = ? AND deleted_at IS NULL",
        (qb_id,),
    ).fetchone()
    if not row:
        return None
    try:
        oq = json.loads(row["original_questions"] or "[]")
    except Exception:
        oq = []
    if not (0 <= variant_index < len(oq)):
        return None
    variant = oq[variant_index]
    from app.services.question_variant_reconciliation import (
        assert_no_other_variant_owner,
        claim_original_question_owner,
    )

    # A legacy pending split can outlive another repair that already created
    # the independent cluster. Do not create a second one from the stale card.
    assert_no_other_variant_owner(conn, variant, {qb_id})
    new_rep = (new_representative or "").strip() or variant
    new_cat2_val = (new_cat2 or "").strip() or row["cat2"] or ""

    new_oq = [q for i, q in enumerate(oq) if i != variant_index]
    conn.execute(
        "UPDATE question_bank SET original_questions = ?, frequency = ? WHERE id = ?",
        (json.dumps(new_oq, ensure_ascii=False), max(len(new_oq), 1), qb_id),
    )
    cur = conn.execute(
        "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, "
        "status, owner_id, job_position, original_questions, sources) "
        "VALUES (?, ?, ?, ?, ?, 1, 'approved', ?, ?, ?, ?)",
        (
            new_rep,
            row["cat1"] or "",
            new_cat2_val,
            row["tags"] or "",
            row["difficulty"] or "L2-中等",
            row["owner_id"] if "owner_id" in row.keys() else None,
            row["job_position"] or "",
            json.dumps([variant], ensure_ascii=False),
            row["sources"] or "[]",
        ),
    )
    conn.execute("UPDATE question_bank SET cluster_id = ? WHERE id = ?", (cur.lastrowid, cur.lastrowid))
    claim_original_question_owner(conn, variant, cur.lastrowid)
    _sync_question_cluster_normalized_tables(conn, qb_id)
    _sync_question_cluster_normalized_tables(conn, cur.lastrowid)
    from app.services.cluster_review_lifecycle import mark_clusters_review_pending

    mark_clusters_review_pending(conn, [qb_id, cur.lastrowid], "split_cluster")
    return cur.lastrowid


def dedupe_variant(conn, qb_id: int, variant_indices: list[int]) -> int:
    """去重重复变体：移除指定变体 + frequency 相应减少（保留代表题）。

    Returns: 移除的变体数
    """
    row = conn.execute(
        "SELECT original_questions FROM question_bank WHERE id = ? AND deleted_at IS NULL",
        (qb_id,),
    ).fetchone()
    if not row:
        return 0
    try:
        oq = json.loads(row["original_questions"] or "[]")
    except Exception:
        oq = []
    drop = {i for i in variant_indices if 0 <= i < len(oq)}
    if not drop:
        return 0
    new_oq = [q for i, q in enumerate(oq) if i not in drop]
    conn.execute(
        "UPDATE question_bank SET original_questions = ?, frequency = ? WHERE id = ?",
        (json.dumps(new_oq, ensure_ascii=False), max(len(new_oq), 1), qb_id),
    )
    _sync_question_cluster_normalized_tables(conn, qb_id)
    from app.services.question_variant_reconciliation import rebuild_variant_ownership

    rebuild_variant_ownership(conn)
    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

    mark_cluster_review_pending(conn, qb_id, "dedupe_variant")
    return len(drop)


def merge_variant(conn, source_qb_id: int, variant_index: int, target_qb_id: int) -> bool:
    """并入误合并变体：从来源题移除该变体 + frequency-1，加入目标题 + frequency+1。

    误合并的问法若更适合并入其他题（跨 cat2 也允许），则不拆成独立题。
    执行前重检：来源题 oq 中不存在该下标 → False；目标题不存在 → False。
    Returns: 是否成功
    """
    src = conn.execute(
        "SELECT original_questions FROM question_bank WHERE id = ? AND deleted_at IS NULL",
        (source_qb_id,),
    ).fetchone()
    if not src:
        return False
    try:
        src_oq = json.loads(src["original_questions"] or "[]")
    except Exception:
        src_oq = []
    if not (0 <= variant_index < len(src_oq)):
        return False
    variant = src_oq[variant_index]

    tgt = conn.execute(
        "SELECT original_questions FROM question_bank WHERE id = ? AND deleted_at IS NULL",
        (target_qb_id,),
    ).fetchone()
    if not tgt:
        return False
    try:
        tgt_oq = json.loads(tgt["original_questions"] or "[]")
    except Exception:
        tgt_oq = []
    # 目标题已含该问法 → 直接从来源题移除即可（去重效果），不重复添加
    new_src_oq = [q for i, q in enumerate(src_oq) if i != variant_index]
    conn.execute(
        "UPDATE question_bank SET original_questions = ?, frequency = ? WHERE id = ?",
        (json.dumps(new_src_oq, ensure_ascii=False), max(len(new_src_oq), 1), source_qb_id),
    )
    if variant not in tgt_oq:
        tgt_oq.append(variant)
        conn.execute(
            "UPDATE question_bank SET original_questions = ?, frequency = ? WHERE id = ?",
            (json.dumps(tgt_oq, ensure_ascii=False), len(tgt_oq), target_qb_id),
        )
    from app.services.question_variant_reconciliation import transfer_original_question_owner

    transfer_original_question_owner(conn, variant, source_qb_id, target_qb_id)
    _sync_question_cluster_normalized_tables(conn, source_qb_id)
    _sync_question_cluster_normalized_tables(conn, target_qb_id)
    from app.services.cluster_review_lifecycle import mark_clusters_review_pending

    mark_clusters_review_pending(conn, [source_qb_id, target_qb_id], "merge_variant")
    return True


def refine_representative(conn, qb_id: int, new_representative: str) -> bool:
    """精炼代表题：LLM 建议的规范题面入 question，原代表题进 oq（保真，可回滚）。

    new_representative 为空/与现代表题相同 → False。
    """
    if not new_representative or not new_representative.strip():
        return False
    new_rep = new_representative.strip()
    row = conn.execute(
        "SELECT question, original_questions FROM question_bank WHERE id = ? AND deleted_at IS NULL",
        (qb_id,),
    ).fetchone()
    if not row or row["question"] == new_rep:
        return False
    try:
        oq = json.loads(row["original_questions"] or "[]")
    except Exception:
        oq = []
    if row["question"] not in oq:
        oq.insert(0, row["question"])
    from app.services.question_variant_reconciliation import claim_original_question_owner

    claim_original_question_owner(conn, row["question"], qb_id)
    conn.execute(
        "UPDATE question_bank SET question = ?, original_questions = ?, frequency = ? WHERE id = ?",
        (new_rep, json.dumps(oq, ensure_ascii=False), len(oq), qb_id),
    )
    _sync_question_cluster_normalized_tables(conn, qb_id)
    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

    mark_cluster_review_pending(conn, qb_id, "representative_changed")
    return True


# ── 审查清单生成（两轮确认 + 置信度分级）──

CONFIRM_ISSUE_PROMPT = """你是面试题去重专家。以下是聚类中的【代表题】和【被标记的问题变体】。

第一轮审查标记该变体与代表题考察点不一致（疑似误合并）。请**独立确认**：
该变体是否真的与代表题属于不同考察点（确实应该拆出/修正）？
注意：不要因为表述差异就确认；只有考察点确实不同才算问题。

【代表题】
{representative}

【问题变体】
{variant}

输出格式（严格 JSON）：{{"confirm": true 或 false, "confidence": 0.0-1.0, "reason": "一句话"}}"""

SPLIT_REWRITE_PROMPT = """你是面试题题库管理专家。误合并的一个问法将被拆成独立题，但该问法来自访谈现场，
脱离上下文后可能不自明（如「关于研究生方向…」）。请基于以下信息，把它重写为
一个**自明、规范、面试官能直接提问**的独立题面（20-40 字），并从可选分类中
判定该新题最匹配的 cat2（分类）。

要求：
- 保留原问法的核心考察点，不改变语义
- 补充必要的上下文，使其脱离访谈也能看懂
- 不要用「关于」「对于」这类含糊开头，要像一道完整面试题
- cat2 只能从【可选分类】中选一个，不得发明新分类

【被拆出的原题目】
{original}

【来源代表题】（该问法原本所属的题）
{representative}

【同来源其他问法】
{others}

【可选分类（cat2）】
{categories}

输出格式（严格 JSON）：{{"rewritten": "重写后的规范题面", "cat2": "最匹配的分类", "reason": "一句话说明为什么这样重写"}}"""

FIND_MERGE_TARGET_PROMPT = """你是面试题去重专家。一个问法被误合并进了某道题（考察点不同），需要判断它更适合
「并入到另一道更合适的题」还是「拆成独立题」。

请从候选目标题中判断：是否存在一道题，该问法的考察点**正好属于**它的范围（并入后不违和）。
若存在，返回最合适的一道（可跨分类，只要语义匹配）；若都不合适，说明该问法应拆成独立题。

【被并入的问法】
{variant}

【来源代表题】（当前误合并所在题）
{source}

【候选目标题】
{candidates}

输出格式（严格 JSON）：{{"merge": true 或 false, "target_qb_id": 整数或 null, "reason": "一句话"}}"""

# 置信度分级（业界实践：Claro 三级阈值）
ISSUE_CONFIDENCE_HIGH = 0.85   # 高置信：可批量审批
ISSUE_CONFIDENCE_LOW = 0.50    # 低于此置信度不进清单（丢弃记录）


async def generate_quality_issues(
    user_id: int = None,
    limit: int = 20,
    cluster_ids: list[int] | None = None,
    review_version: str | None = None,
    review_task_id: str | None = None,
    trigger_reason: str | None = None,
) -> dict:
    """审查发现的问题 → 两轮确认 → quality_issue 清单。

    两轮确认（验证层思想）：第一轮核验（run_quality_audit 的 inconsistent 变体）
    → 第二轮独立确认（本函数）→ 两轮一致才生成 issue。
    """
    from app.db.connection import get_db_connection
    from app.services.llm import _call_llm_with_retry
    from app.services.llm_judge import parse_json_object

    with get_db_connection() as conn:
        where = (
            "WHERE deleted_at IS NULL AND owner_id IS NULL AND frequency > 1 "
        )
        params = []
        if cluster_ids:
            placeholders = ",".join("?" * len(cluster_ids))
            where += f"AND id IN ({placeholders}) "
            params.extend(cluster_ids)
            order_limit = ""
        else:
            order_limit = " LIMIT ?"
            params.append(limit)
        rows = conn.execute(
            "SELECT id, question, cat1, cat2, frequency, original_questions FROM question_bank "
            + where
            + "ORDER BY frequency DESC"
            + order_limit,
            params,
        ).fetchall()

    candidates = []
    for r in rows:
        try:
            oq = json.loads(r["original_questions"] or "[]")
        except Exception:
            oq = []
        oq = [str(q).strip() for q in oq if str(q).strip()]
        if len(oq) >= 2:
            candidates.append({
                "id": r["id"],
                "question": r["question"],
                "cat1": r["cat1"] or "",
                "cat2": r["cat2"] or "",
                "oq": oq,
            })

    # 岗位分类体系（cat2 候选）：LLM 拆出重写时判定新题分类，不发明新分类
    from app.db.queries import get_taxonomy_for_position

    taxonomy = get_taxonomy_for_position()
    cat2_candidates = []
    for _c in taxonomy.get("categories", []) or []:
        for _child in (_c.get("children") or []):
            if _child:
                cat2_candidates.append(str(_child))
    categories_text = "\n".join(f"- {c}" for c in cat2_candidates) or "（无）"

    created = 0
    for rep in candidates:
        for idx, variant in enumerate(rep["oq"]):
            if variant == rep["question"]:
                continue  # 代表题自身不是问题
            prompt = CONFIRM_ISSUE_PROMPT.format(
                representative=rep["question"], variant=variant
            )
            try:
                raw = await _call_llm_with_retry(
                    prompt, system_msg="你是一个面试题去重专家。",
                    response_format=None, user_id=user_id, model=None,
                )
                data = parse_json_object(raw) or {}
                confirmed = bool(data.get("confirm"))
                confidence = float(data.get("confidence", 0))
            except Exception as e:
                logger.warning(f"[清单生成] 确认失败 qb={rep['id']} idx={idx}: {e}")
                continue
            if not confirmed or confidence < ISSUE_CONFIDENCE_LOW:
                continue  # 未确认或低置信 → 不进清单

            # 判断「并入其他题」还是「拆成独立题」：跨 cat2 也允许并入（语义匹配为准）
            merge_target = None
            try:
                with get_db_connection() as conn2:
                    merge_cands = conn2.execute(
                        "SELECT id, question, cat1, cat2 FROM question_bank "
                        "WHERE deleted_at IS NULL AND owner_id IS NULL AND id != ? "
                        "AND frequency > 0 "
                        "ORDER BY (cat1 = ?) DESC, frequency DESC LIMIT 6",
                        (rep["id"], rep["cat1"]),
                    ).fetchall()
                cand_text = "\n".join(
                    f"- #{c['id']}: {c['question']}（{c['cat1']}/{c['cat2']}）" for c in merge_cands
                ) or "（无）"
                mraw = await _call_llm_with_retry(
                    FIND_MERGE_TARGET_PROMPT.format(
                        variant=variant, source=rep["question"], candidates=cand_text,
                    ),
                    system_msg="你是一个面试题去重专家。",
                    response_format=None, user_id=user_id, model=None,
                )
                mdata = parse_json_object(mraw) or {}
                if mdata.get("merge"):
                    merge_target = mdata.get("target_qb_id")
                    # 校验目标题确实是候选之一（防 LLM 编造 id）
                    valid_ids = {c["id"] for c in merge_cands}
                    if merge_target not in valid_ids:
                        merge_target = None
            except Exception as e:
                logger.warning(f"[清单生成] 并入判定失败 qb={rep['id']} idx={idx}: {e}")

            if merge_target is not None:
                # 并入路径：来源题移除该问法，目标题加问法
                with get_db_connection() as conn:
                    from app.services.cluster_review_lifecycle import get_current_cluster_version

                    current_review_version = get_current_cluster_version(conn, rep["id"])
                    if not current_review_version:
                        continue
                    if review_version and current_review_version != review_version:
                        continue
                    dup = conn.execute(
                        "SELECT id FROM quality_issue WHERE qb_id = ? "
                        "AND issue_type = 'mismerge' AND "
                        "(variant_key = ? AND review_version = ? OR "
                        "variant_index = ? AND review_version IS NULL "
                        "AND status IN ('pending', 'approved'))",
                        (rep["id"], str(idx), current_review_version, idx),
                    ).fetchone()
                    if dup:
                        continue
                    _, inserted = upsert_quality_issue(conn, {
                        "qb_id": rep["id"],
                        "variant_index": idx,
                        "issue_type": "mismerge",
                        "suggested_action": "merge",
                        "reason": data.get("reason", "")[:300],
                        "suggested_value": None,
                        "confidence": round(confidence, 2),
                        "status": "pending",
                        "target_qb_id": merge_target,
                        "new_cat2": None,
                        "source_question": variant,
                        "source_cat2": rep["cat2"],
                        "review_version": current_review_version,
                        "review_task_id": review_task_id,
                        "trigger_reason": trigger_reason or "manual_quality_scan",
                        "variant_key": str(idx),
                        "issue_fingerprint": build_issue_fingerprint("mismerge", variant),
                    })
                    conn.commit()
                created += int(inserted)
                continue

            # 拆成独立题：预生成重写题面（原题目脱离上下文可能不自明，需补偿）
            rewritten = None
            new_cat2 = None
            others = [q for i2, q in enumerate(rep["oq"]) if i2 != idx and q != variant][:5]
            try:
                raw = await _call_llm_with_retry(
                    SPLIT_REWRITE_PROMPT.format(
                        original=variant,
                        representative=rep["question"],
                        others="\n".join(f"- {o}" for o in others) or "（无）",
                        categories=categories_text,
                    ),
                    system_msg="你是一个面试题题库管理专家。",
                    response_format=None, user_id=user_id, model=None,
                )
                data = parse_json_object(raw) or {}
                rewritten = (data.get("rewritten") or "").strip() or None
                new_cat2 = (data.get("cat2") or "").strip() or None
            except Exception as e:
                logger.warning(f"[清单生成] 拆出重写失败 qb={rep['id']} idx={idx}: {e}")
            # 已存在相同 issue → 跳过（幂等）
            with get_db_connection() as conn:
                from app.services.cluster_review_lifecycle import get_current_cluster_version

                current_review_version = get_current_cluster_version(conn, rep["id"])
                if not current_review_version:
                    continue
                if review_version and current_review_version != review_version:
                    continue
                dup = conn.execute(
                    "SELECT id FROM quality_issue WHERE qb_id = ? "
                    "AND issue_type = 'mismerge' AND "
                    "(variant_key = ? AND review_version = ? OR "
                    "variant_index = ? AND review_version IS NULL "
                    "AND status IN ('pending', 'approved'))",
                    (rep["id"], str(idx), current_review_version, idx),
                ).fetchone()
                if dup:
                    continue
                _, inserted = upsert_quality_issue(conn, {
                    "qb_id": rep["id"],
                    "variant_index": idx,
                    "issue_type": "mismerge",
                    "suggested_action": "split",
                    "reason": data.get("reason", "")[:300],
                    "suggested_value": rewritten,
                    "confidence": round(confidence, 2),
                    "status": "pending",
                    "target_qb_id": None,
                    "new_cat2": new_cat2,
                    "source_question": variant,
                    "source_cat2": rep["cat2"],
                    "review_version": current_review_version,
                    "review_task_id": review_task_id,
                    "trigger_reason": trigger_reason or "manual_quality_scan",
                    "variant_key": str(idx),
                    "issue_fingerprint": build_issue_fingerprint("mismerge", variant),
                })
                conn.commit()
            created += int(inserted)
    logger.info("[清单生成] 新增 issue: %d 条", created)
    return {"created": created, "scanned_cluster_ids": [c["id"] for c in candidates]}


# ── weak_representative 检测 + 规范题面建议（LLM 生成）──

WEAK_REPRESENTATIVE_PROMPT = """你是面试题题库管理专家。以下是【代表题】和它的【原始题面变体】。

请判断代表题是否**足够规范**（能涵盖所有变体的核心考察点、表述完整具体）。
若不够规范（过于简略、口语化、遗漏部分变体的考察点），请基于全部变体生成一个
**更规范的题面建议**（20-40 字，覆盖所有变体的考察点，去除面试现场口语）。

【代表题】
{representative}

【变体列表】
{variants}

输出格式（严格 JSON）：
{{"weak": true 或 false, "suggested": "规范题面建议（weak=true 时必填）或 null",
  "reason": "一句话原因"}}"""


async def generate_weak_representative_issues(
    user_id: int = None,
    limit: int = 20,
    cluster_ids: list[int] | None = None,
    review_version: str | None = None,
    review_task_id: str | None = None,
    trigger_reason: str | None = None,
) -> dict:
    """检测代表题过弱的聚类 → 生成 weak_representative issue（含 LLM 建议题面）。

    幂等：已存在 pending/approved 的 weak_representative issue → 跳过。
    """
    from app.db.connection import get_db_connection
    from app.services.llm import _call_llm_with_retry
    from app.services.llm_judge import parse_json_object

    with get_db_connection() as conn:
        where = (
            "WHERE deleted_at IS NULL AND owner_id IS NULL AND frequency > 1 "
        )
        params = []
        if cluster_ids:
            placeholders = ",".join("?" * len(cluster_ids))
            where += f"AND id IN ({placeholders}) "
            params.extend(cluster_ids)
            order_limit = ""
        else:
            params.append(limit)
            order_limit = " LIMIT ?"
        rows = conn.execute(
            "SELECT id, question, frequency, original_questions FROM question_bank "
            + where
            + "ORDER BY frequency DESC"
            + order_limit,
            params,
        ).fetchall()

    created = 0
    for r in rows:
        try:
            oq = json.loads(r["original_questions"] or "[]")
        except Exception:
            oq = []
        oq = [str(q).strip() for q in oq if str(q).strip()]
        if not oq:
            continue
        # 代表题是否覆盖完整，必须基于该聚类的全部原始变体判断。
        # 这里不能像展示列表一样截断，否则遗漏的长尾变体可能正是
        # 代表题没有覆盖的考察点。
        variants_text = "\n".join(f"{i}. {v}" for i, v in enumerate(oq))
        prompt = WEAK_REPRESENTATIVE_PROMPT.format(
            representative=r["question"], variants=variants_text
        )
        try:
            raw = await _call_llm_with_retry(
                prompt, system_msg="你是一个面试题题库管理专家。",
                response_format=None, user_id=user_id, model=None,
            )
            data = parse_json_object(raw) or {}
        except Exception as e:
            logger.warning(f"[代表题评估] qb={r['id']} 失败: {e}")
            continue
        if not data.get("weak"):
            continue
        suggested = (data.get("suggested") or "").strip()
        if not suggested or suggested == r["question"]:
            continue
        with get_db_connection() as conn:
            from app.services.cluster_review_lifecycle import get_current_cluster_version

            current_review_version = get_current_cluster_version(conn, r["id"])
            if not current_review_version:
                continue
            if review_version and current_review_version != review_version:
                continue
            dup = conn.execute(
                "SELECT id FROM quality_issue WHERE qb_id = ? "
                "AND issue_type = 'weak_representative' AND "
                "(variant_key = '' AND review_version = ? OR "
                "review_version IS NULL AND status IN ('pending', 'approved'))",
                (r["id"], current_review_version),
            ).fetchone()
            if dup:
                continue
            _, inserted = upsert_quality_issue(conn, {
                "qb_id": r["id"],
                "variant_index": None,
                "issue_type": "weak_representative",
                "suggested_action": "refine_representative",
                "reason": data.get("reason", "")[:300],
                "suggested_value": suggested,
                "confidence": 0.7,
                "status": "pending",
                "target_qb_id": None,
                "new_cat2": None,
                "source_question": None,
                "source_cat2": None,
                "review_version": current_review_version,
                "review_task_id": review_task_id,
                "trigger_reason": trigger_reason or "manual_quality_scan",
                "variant_key": "",
                "issue_fingerprint": build_issue_fingerprint(
                    "weak_representative", r["question"], qb_id=r["id"]
                ),
            })
            conn.commit()
        created += int(inserted)
    logger.info("[代表题评估] 新增 weak_representative issue: %d 条", created)
    return {"created": created}

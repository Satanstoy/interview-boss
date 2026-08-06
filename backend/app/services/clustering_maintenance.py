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
        keep, drop = min(pair), max(pair)  # 保留较小下标
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
            "WHERE deleted_at IS NULL AND frequency > 1 "
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
    lines = [f"# 聚类质量定期审查报告", "",
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

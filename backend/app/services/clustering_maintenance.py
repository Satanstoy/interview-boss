"""Clustering maintenance and deterministic data repair.

This module keeps admin routes thin and centralizes safe repairs for
question_bank clustering metadata. It deliberately avoids using embedding
thresholds as merge decisions.
"""
import json
import logging
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from app.db.question_bank_sources import delete_all_for_qb, insert_original_item, insert_source

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
        (s.get("url", ""), s.get("company", ""), s.get("round", ""))
        for s in merged
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
        insert_source(conn, qb_id, src.get("url", ""), src.get("company", ""), src.get("round", ""))
    for item in original_sources:
        if not isinstance(item, dict):
            continue
        insert_original_item(conn, qb_id, item.get("question", ""), item.get("sources", []))


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
            exact_groups[norm].append({
                "id": row["id"],
                "question": row["question"],
                "cat2": row.get("cat2") or "",
                "frequency": row.get("frequency") or 0,
            })

    exact_duplicate_groups = [
        {"normalized": key, "items": items}
        for key, items in exact_groups.items()
        if len(items) > 1
    ]

    normalized_counts = {
        "question_sources": conn.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0],
        "question_original_items": conn.execute("SELECT COUNT(*) FROM question_original_items").fetchone()[0],
        "question_original_item_sources": conn.execute("SELECT COUNT(*) FROM question_original_item_sources").fetchone()[0],
    }

    freq_mismatch = []
    normalized_mismatch = []
    for row in rows:
        originals, _ = _canonical_cluster_payload(row)
        expected = max(1, len(originals))
        if (row.get("frequency") or 0) != expected:
            freq_mismatch.append({
                "id": row["id"],
                "frequency": row.get("frequency") or 0,
                "expected": expected,
                "question": row["question"],
            })
        qoi_count = conn.execute(
            "SELECT COUNT(*) FROM question_original_items WHERE question_bank_id = ?",
            (row["id"],),
        ).fetchone()[0]
        if qoi_count != len(originals):
            normalized_mismatch.append({
                "id": row["id"],
                "normalized_original_count": qoi_count,
                "expected": len(originals),
            })

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
    return {"survivor_id": survivor_id, "merged_id": merged_id, "question": row["question"]}


def run_clustering_maintenance(conn, execute: bool = False, merge_exact_duplicates: bool = True) -> Dict:
    """Audit clustering data and optionally apply deterministic repairs."""
    before = audit_clustering_state(conn)
    if not execute:
        return {"dry_run": True, "audit": before, "applied": {"metadata": [], "exact_merges": []}}

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
                items = sorted(group["items"], key=lambda x: (-(x["frequency"] or 0), x["id"]))
                survivor = items[0]
                for item in items[1:]:
                    result = _merge_exact_duplicate_pair(conn, survivor["id"], item["id"])
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

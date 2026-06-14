"""Weighted question drawing for interview agents and practice APIs."""

from __future__ import annotations

import random
import time
from datetime import datetime
from math import log1p, sqrt
from typing import Optional

from app.db.connection import get_db_connection, get_dynamic_frequency_sql
from app.db.question_bank_sources import get_sources
from app.routers.questions import _build_bank_where_clause


def _map_difficulty(difficulty: str) -> list[str]:
    """Map English difficulty levels to database-matching patterns.

    The question_bank stores difficulty as Chinese labels like 'L1-基础',
    'L2-中等', 'L3-困难', or plain '简单/中等/困难'.  The LLM typically
    sends 'easy', 'medium', 'hard'.  This function returns a list of LIKE
    patterns so the caller can use ``qb.difficulty LIKE ? OR qb.difficulty LIKE ?``.
    """
    mapping = {
        "easy": ["L1%", "%基础%", "%简单%"],
        "medium": ["L2%", "%中等%"],
        "hard": ["L3%", "%困难%"],
    }
    lower = (difficulty or "").strip().lower()
    return mapping.get(lower, [f"%{difficulty}%"])


def draw_questions(
    *,
    user: dict,
    count: int = 5,
    cat1: Optional[str] = None,
    cat2: Optional[str] = None,
    topic: Optional[str] = None,
    difficulty: Optional[str] = None,
    question_type: Optional[str] = None,
    exclude_ids: Optional[set[int]] = None,
) -> list[dict]:
    """Draw weighted random questions visible to the current user.

    This is intentionally synchronous so it can be used from normal FastAPI
    threadpool calls and from LangGraph nodes that already run in-process.

    When *difficulty* is supplied but yields zero candidates, the function
    automatically retries without the difficulty filter so that callers like
    ``draw_questions(question_type='algorithm_coding', difficulty='medium')``
    still get results even if the database stores Chinese difficulty labels.
    """
    count = max(1, min(int(count or 5), 50))
    exclude_ids = exclude_ids or set()
    from_clause, where_clause, base_params = _build_bank_where_clause(user, "qb")
    bank_mode = user.get("bank_mode", "public")

    def _query(extra_conditions: list[str], extra_params: list) -> list:
        where_with_extra = where_clause
        if extra_conditions:
            where_with_extra = f"{where_clause} AND {' AND '.join(extra_conditions)}"
        dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user["id"])
        return conn.execute(
            f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, "
            f"({dyn_freq_sql}) as frequency, qb.ai_answer "
            f"{from_clause} {where_with_extra}",
            extra_params,
        ).fetchall()

    with get_db_connection() as conn:
        conditions = []
        params = list(base_params)
        if cat1 and cat1 != "全部":
            conditions.append("(qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ?)")
            params.extend([f"%{cat1}%", f"%{cat1}%", f"%{cat1}%"])
        if cat2 and cat2 != "全部":
            conditions.append("(qb.cat2 LIKE ? OR qb.tags LIKE ?)")
            params.extend([f"%{cat2}%", f"%{cat2}%"])
        if topic:
            conditions.append(
                "(qb.question LIKE ? OR qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ?)"
            )
            params.extend([f"%{topic}%"] * 4)
        difficulty_applied = False
        if difficulty:
            diff_patterns = _map_difficulty(difficulty)
            diff_ors = " OR ".join("qb.difficulty LIKE ?" for _ in diff_patterns)
            conditions.append(f"({diff_ors})")
            params.extend(diff_patterns)
            difficulty_applied = True
        if question_type:
            type_conditions, type_params = _question_type_filter(question_type)
            if type_conditions:
                conditions.append(type_conditions)
                params.extend(type_params)
        if exclude_ids:
            placeholders = ",".join("?" * len(exclude_ids))
            conditions.append(f"qb.id NOT IN ({placeholders})")
            params.extend(sorted(exclude_ids))

        candidates = _query(conditions, params)

        # Fallback: if difficulty filter yielded nothing, retry without it
        if not candidates and difficulty_applied:
            fallback_conditions = [c for c in conditions if "qb.difficulty" not in c]
            # Rebuild params without difficulty so placeholder order stays exact.
            fallback_params = list(base_params)
            if cat1 and cat1 != "全部":
                fallback_params.extend([f"%{cat1}%", f"%{cat1}%", f"%{cat1}%"])
            if cat2 and cat2 != "全部":
                fallback_params.extend([f"%{cat2}%", f"%{cat2}%"])
            if topic:
                fallback_params.extend([f"%{topic}%"] * 4)
            if question_type:
                _, type_params = _question_type_filter(question_type)
                fallback_params.extend(type_params)
            if exclude_ids:
                fallback_params.extend(sorted(exclude_ids))
            candidates = _query(fallback_conditions, fallback_params)

        if not candidates:
            return []

        ids = [r["id"] for r in candidates]
        placeholders = ",".join("?" * len(ids))
        stats = conn.execute(
            f"SELECT question_bank_id, COUNT(*) as cnt, MAX(created_at) as last_at "
            f"FROM user_practice_history "
            f"WHERE user_id = ? AND question_bank_id IN ({placeholders}) "
            f"GROUP BY question_bank_id",
            [user["id"]] + ids,
        ).fetchall()

        practice_map = {}
        now = time.time()
        for s in stats:
            qid = s["question_bank_id"]
            last_at = s["last_at"]
            try:
                last_dt = datetime.fromisoformat(last_at)
                hours_ago = (now - last_dt.timestamp()) / 3600
            except Exception:
                hours_ago = 9999
            practice_map[qid] = {
                "count": s["cnt"],
                "hours_ago": hours_ago,
                "last_at": last_at,
            }

        selected_indices = _weighted_sample_without_replacement(
            candidates, practice_map, count
        )
        selected_ids = [candidates[idx]["id"] for idx in selected_indices]
        try:
            sources_map = {qid: get_sources(conn, qid) for qid in selected_ids}
        except Exception:
            sources_map = {}

    result = []
    for idx in selected_indices:
        row = candidates[idx]
        item = dict(row)
        item["sources"] = sources_map.get(row["id"], [])
        info = practice_map.get(row["id"])
        item["attempt_count"] = info["count"] if info else 0
        item["last_practiced_at"] = info.get("last_at") if info else None
        result.append(item)
    return result


def _question_type_filter(question_type: str) -> tuple[str, list[str]]:
    """Map agent question_type to coarse question bank filters."""
    if question_type == "algorithm_coding":
        return (
            "(qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ? OR qb.question LIKE ?)",
            ["%算法%", "%算法%", "%算法%", "%代码%"],
        )
    if question_type == "project_followup":
        return (
            "(qb.cat1 LIKE ? OR qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ?)",
            ["%项目%", "%Agent%", "%系统设计%", "%项目%"],
        )
    if question_type == "knowledge_probe":
        return (
            "(qb.cat1 LIKE ? OR qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ?)",
            ["%基础%", "%Agent%", "%RAG%", "%原理%"],
        )
    if question_type == "system_design":
        return (
            "(qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ?)",
            ["%系统设计%", "%系统设计%", "%架构%"],
        )
    if question_type == "hr":
        return (
            "(qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ?)",
            ["%HR%", "%行为%", "%软技能%"],
        )
    return (
        "(qb.cat1 LIKE ? OR qb.cat2 LIKE ? OR qb.tags LIKE ?)",
        [f"%{question_type}%", f"%{question_type}%", f"%{question_type}%"],
    )


def _weighted_sample_without_replacement(
    candidates: list, practice_map: dict[int, dict], count: int
) -> list[int]:
    weights = []
    for row in candidates:
        qid = row["id"]
        frequency = max(float(row["frequency"] or 1), 1.0)
        frequency_weight = 1.0 + sqrt(frequency) + log1p(frequency)
        if qid not in practice_map:
            recency_weight = 1.2
        else:
            info = practice_map[qid]
            recency_weight = 1.0 / (1 + info["count"] * 0.35)
            if info["hours_ago"] < 24:
                recency_weight *= 0.25
            elif info["hours_ago"] < 72:
                recency_weight *= 0.65
        weights.append(max(frequency_weight * recency_weight, 0.01))

    selected_indices = []
    remaining = list(range(len(candidates)))
    remaining_weights = list(weights)
    for _ in range(min(count, len(candidates))):
        total = sum(remaining_weights)
        if total <= 0:
            break
        pick = random.random() * total
        cumulative = 0.0
        chosen_idx = 0
        for i, weight in enumerate(remaining_weights):
            cumulative += weight
            if cumulative >= pick:
                chosen_idx = i
                break
        selected_indices.append(remaining[chosen_idx])
        remaining.pop(chosen_idx)
        remaining_weights.pop(chosen_idx)
    return selected_indices

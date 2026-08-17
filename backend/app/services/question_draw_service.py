"""Weighted question drawing for interview agents and practice APIs."""

from __future__ import annotations

import logging
import re
import random
import time
from datetime import datetime
from math import log1p, sqrt
from typing import Optional

logger = logging.getLogger("interview-boss")

from app.db import connection as db_connection
from app.db.question_bank_sources import get_sources
from app.db.queries import build_bank_where_clause
from app.services.interview_distribution import (
    BEHAVIORAL_ACRONYM_TERMS,
    BEHAVIORAL_SIGNAL_TERMS,
)


def get_db_connection():
    return db_connection.get_db_connection()


def get_dynamic_frequency_sql(bank_mode: str, user_id: int) -> str:
    return db_connection.get_dynamic_frequency_sql(bank_mode, user_id)


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


def _embedding_supplement(
    *,
    conn,
    query_text: str,
    existing_ids: set[int],
    exclude_ids: set[int],
    limit: int,
) -> list:
    """SQL 候选不足时，用 embedding 语义补充候选（实验结论 P1b）。

    生产 embedding 为 bge-m3（SiliconFlow，1024 维）。任何失败优雅降级返回 []。
    """
    if limit <= 0:
        return []
    try:
        import struct

        from app.services.embedding_service import encode_texts

        query_vec = encode_texts([query_text])[0]
        if hasattr(query_vec, "tolist"):
            query_vec = query_vec.tolist()
    except Exception:
        return []

    rows = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, ai_answer, embedding "
        "FROM question_bank "
        "WHERE deleted_at IS NULL AND status = 'approved' AND embedding IS NOT NULL"
    ).fetchall()

    def _cosine(emb_bytes):
        try:
            n = len(emb_bytes) // 4
            vec = struct.unpack(f"<{n}f", emb_bytes)
            if len(vec) != len(query_vec):
                return 0.0
            dot = sum(a * b for a, b in zip(query_vec, vec))
            na = sum(x * x for x in query_vec) ** 0.5
            nb = sum(x * x for x in vec) ** 0.5
            return dot / (na * nb + 1e-9) if na and nb else 0.0
        except Exception:
            return 0.0

    scored = []
    for r in rows:
        qid = r["id"]
        if qid in existing_ids or qid in exclude_ids:
            continue
        scored.append((_cosine(r["embedding"]), r))
    scored.sort(key=lambda t: t[0], reverse=True)
    # ``embedding`` is an internal BLOB used only for ranking.  Never return
    # it in a question payload: the result is copied into the chat session
    # state, which must remain JSON serializable for Redis/SQLite persistence.
    result = []
    for _, row in scored[:limit]:
        item = dict(row)
        item.pop("embedding", None)
        result.append(item)
    return result


# 触发 embedding 补充的候选池下限（实验结论：SQL 候选萎缩是抽题 0 分主因）
_EMBEDDING_MIN_POOL = 5


def draw_questions(
    *,
    user: dict,
    count: int = 5,
    cat1: Optional[str] = None,
    cat2: Optional[str] = None,
    topic: Optional[str] = None,
    difficulty: Optional[str] = None,
    question_type: Optional[str] = None,
    job_position: Optional[str] = None,
    job_position_id: Optional[int] = None,
    exclude_ids: Optional[set[int]] = None,
    session_notes: Optional[str] = None,
    max_per_category: int = 2,
) -> list[dict]:
    """Draw weighted random questions visible to the current user.

    This is intentionally synchronous so it can be used from normal FastAPI
    threadpool calls and from LangGraph nodes that already run in-process.

    When *difficulty* is supplied but yields zero candidates, the function
    retries within the same position and bank scope without that presentation
    filter.  It never drops the position join or switches to another bank.
    """
    count = max(1, min(int(count or 5), 50))
    exclude_ids = exclude_ids or set()
    bank_mode = str(user.get("bank_mode") or "all").lower()
    filter_mode = {
        "public": "public",
        "mine": "mine",
        "personal": "mine",
        "mixed": "all",
        "all": "all",
    }.get(bank_mode, "all")
    if job_position:
        from_clause, where_clause, base_params = build_bank_where_clause(
            user["id"],
            filter_mode,
            "qb",
            job_position=job_position,
            job_position_id=job_position_id,
        )
    else:
        # Preserve the established call shape for internal callers and test
        # adapters that provide the legacy three-argument helper.
        from_clause, where_clause, base_params = build_bank_where_clause(
            user["id"], filter_mode, "qb"
        )

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

        # 实验结论 P1b：SQL 候选不足时用 embedding 语义补充（修复 0 题/1 题候选灾难）
        if len(candidates) < _EMBEDDING_MIN_POOL and (cat2 or topic or cat1):
            query_text = " ".join(filter(None, [cat2, topic, cat1])) or "面试题"
            existing_ids = {r["id"] for r in candidates}
            extra = _embedding_supplement(
                conn=conn,
                query_text=query_text,
                existing_ids=existing_ids,
                exclude_ids=exclude_ids,
                limit=_EMBEDDING_MIN_POOL - len(candidates),
            )
            if extra:
                candidates = list(candidates) + extra
                logger.info(
                    "draw_questions: SQL 候选 %d 不足，embedding 补充 %d 题",
                    len(candidates) - len(extra),
                    len(extra),
                )

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
            f"SELECT question_bank_id, COUNT(*) as cnt, MAX(reviewed_at) as last_at "
            f"FROM practice_review_events "
            f"WHERE user_id = ? AND source = 'self_check' AND question_bank_id IN ({placeholders}) "
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

        # Apply per-category quota: remove candidates from categories
        # that have already been asked max_per_category times.
        if session_notes:
            asked_categories = _count_asked_categories(session_notes)
            selected_indices = _apply_category_quota_indices(
                candidates, selected_indices, asked_categories, max_per_category
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


def _query_without_position_filter(
    *,
    conn,
    user: dict,
    bank_mode: str,
    question_type: str,
    job_position: Optional[str],
    cat1: Optional[str],
    cat2: Optional[str],
    topic: Optional[str],
    difficulty: Optional[str],
    exclude_ids: set[int],
    fallback_reason: str,
) -> list[dict]:
    """Retry question drawing without the current job-position join.

    Some interview categories, especially algorithm coding, are general across
    job positions. If a newly-created position has no mapped questions yet, the
    agent should still be able to draw from approved public algorithm questions.
    """

    def _build_conditions(include_difficulty: bool) -> tuple[list[str], list]:
        conditions: list[str] = []
        params: list = []
        if bank_mode in ("all", "mine", "personal", "mixed"):
            conditions.append(
                "((qb.owner_id IS NULL AND qb.status = 'approved') OR qb.owner_id = ?)"
            )
            params.append(user["id"])
        else:  # public
            conditions.append("qb.owner_id IS NULL")
            conditions.append("qb.status = 'approved'")

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
        if include_difficulty and difficulty:
            diff_patterns = _map_difficulty(difficulty)
            diff_ors = " OR ".join("qb.difficulty LIKE ?" for _ in diff_patterns)
            conditions.append(f"({diff_ors})")
            params.extend(diff_patterns)
        type_conditions, type_params = _question_type_filter(question_type)
        if type_conditions:
            conditions.append(type_conditions)
            params.extend(type_params)
        if job_position:
            conditions.append("qb.job_position = ?")
            params.append(job_position)
        if exclude_ids:
            placeholders = ",".join("?" * len(exclude_ids))
            conditions.append(f"qb.id NOT IN ({placeholders})")
            params.extend(sorted(exclude_ids))
        return conditions, params

    dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user["id"])

    def _run(include_difficulty: bool) -> list[dict]:
        conditions, params = _build_conditions(include_difficulty)
        where_clause = " AND ".join(conditions) if conditions else "1 = 1"
        rows = conn.execute(
            f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, "
            f"({dyn_freq_sql}) as frequency, qb.ai_answer "
            f"FROM question_bank qb WHERE {where_clause}",
            params,
        ).fetchall()
        return [
            {
                **dict(row),
                "_fallback_used": True,
                "_fallback_reason": fallback_reason,
            }
            for row in rows
        ]

    candidates = _run(include_difficulty=bool(difficulty))
    if not candidates and difficulty:
        candidates = _run(include_difficulty=False)
    return candidates


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
    if question_type in {"hr", "behavioral"}:
        combined = (
            "(COALESCE(qb.cat1, '') || ' ' || COALESCE(qb.cat2, '') || ' ' "
            "|| COALESCE(qb.tags, '') || ' ' || COALESCE(qb.question, ''))"
        )
        lower_combined = f"LOWER({combined})"
        acronym_conditions: list[str] = []
        acronym_params: list[str] = []
        for acronym in BEHAVIORAL_ACRONYM_TERMS:
            acronym_conditions.extend(
                [
                    f"{lower_combined} = ?",
                    f"{lower_combined} GLOB ?",
                    f"{lower_combined} GLOB ?",
                    f"{lower_combined} GLOB ?",
                ]
            )
            acronym_params.extend(
                [
                    acronym,
                    f"{acronym}[^a-z]*",
                    f"*[^a-z]{acronym}",
                    f"*[^a-z]{acronym}[^a-z]*",
                ]
            )
        return (
            "("
            + " OR ".join(f"{lower_combined} LIKE ?" for _ in BEHAVIORAL_SIGNAL_TERMS)
            + " OR "
            + " OR ".join(acronym_conditions)
            + ")",
            [f"%{term}%" for term in BEHAVIORAL_SIGNAL_TERMS] + acronym_params,
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


def _count_asked_categories(session_notes: str) -> dict[str, int]:
    """Count how many questions from each category have been asked.

    Parses ``[asked] <category>: <question>`` entries from session notes and
    returns a dict mapping category name to the number of times it was asked.
    """
    counts: dict[str, int] = {}
    for match in re.finditer(r"\[asked\]\s*(.+?):", session_notes):
        cat = match.group(1).strip()
        if cat:
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def _apply_category_quota(
    candidates: list[dict],
    asked_categories: dict[str, int],
    max_per_category: int = 2,
) -> list[dict]:
    """Filter candidates, removing questions from categories already at quota.

    Uses the ``cat1`` field of each candidate to check against the asked
    categories count.  If *all* candidates would be filtered out, returns the
    original list as a fallback so the caller always gets something to work
    with.

    Works with both plain dicts and ``sqlite3.Row`` objects.
    """
    filtered = []
    for q in candidates:
        try:
            cat = q["cat1"] or ""
        except (KeyError, IndexError):
            cat = ""
        if asked_categories.get(cat, 0) < max_per_category:
            filtered.append(q)
    return filtered or candidates


def _apply_category_quota_indices(
    candidates: list,
    selected_indices: list[int],
    asked_categories: dict[str, int],
    max_per_category: int = 2,
) -> list[int]:
    """Like _apply_category_quota but operates on index lists.

    Returns a (possibly shorter) list of indices into *candidates* whose
    categories have not yet hit the quota.  Falls back to the original
    *selected_indices* if everything would be removed.
    """
    filtered = []
    for idx in selected_indices:
        try:
            cat = candidates[idx]["cat1"] or ""
        except (KeyError, IndexError):
            cat = ""
        if asked_categories.get(cat, 0) < max_per_category:
            filtered.append(idx)
    return filtered or selected_indices

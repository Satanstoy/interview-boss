"""Rhythm profile learning from approved interview experiences."""

from __future__ import annotations

import re
from collections import Counter

from app.db.connection import get_db_connection

_PHASE_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (
        "system_design",
        re.compile(r"(系统设计|架构设计|高可用|扩展性|可扩展|分布式|scalability)", re.I),
    ),
    (
        "behavioral",
        re.compile(r"(行为面|协作|冲突|失败|复盘|star|影响力|团队)", re.I),
    ),
    (
        "algorithm_coding",
        re.compile(r"(算法|代码|手撕|数据结构|链表|排序|二分|lru|滑动窗口)", re.I),
    ),
    (
        "project_followup",
        re.compile(r"(项目|架构|agent|rag|langgraph|职责|经历|模式)", re.I),
    ),
    (
        "knowledge_probe",
        re.compile(r"(redis|mysql|tcp|http|缓存|锁|线程|进程|索引|持久化)", re.I),
    ),
)


def classify_question_phase(question: str) -> str:
    """Classify a question into a broad interview phase."""

    text = (question or "").strip()
    if not text:
        return "project_followup"

    for phase, pattern in _PHASE_PATTERNS:
        if pattern.search(text):
            return phase
    return "project_followup"


def analyze_topic_distribution(questions: list[str]) -> dict[str, int]:
    """Count question phases in order-independent form."""

    distribution: Counter[str] = Counter()
    for question in questions:
        distribution[classify_question_phase(question)] += 1
    return dict(distribution)


def analyze_topic_transition(questions: list[str]) -> dict[str, dict[str, int]]:
    """Count adjacent phase transitions in an interview question list."""

    transition: dict[str, Counter[str]] = {}
    phases = [classify_question_phase(question) for question in questions]
    for from_phase, to_phase in zip(phases, phases[1:]):
        transition.setdefault(from_phase, Counter())[to_phase] += 1
    return {phase: dict(counts) for phase, counts in transition.items()}


def build_rhythm_profile(
    experience_id: int,
    user_id: int,
    job_position: str,
) -> dict | None:
    """Build a lightweight rhythm profile from an approved accessible experience."""

    with get_db_connection() as conn:
        deleted_at_clause = "AND deleted_at IS NULL" if _has_column(conn, "interview", "deleted_at") else ""
        row = conn.execute(
            f"""
            SELECT id, questions_list, difficulty, job_position, owner_id, status
            FROM interview
            WHERE id = ?
              {deleted_at_clause}
              AND status = 'approved'
              AND (owner_id = ? OR owner_id IS NULL)
              AND (job_position = ? OR job_position = '')
            """,
            (experience_id, user_id, job_position or ""),
        ).fetchone()

    if not row:
        return None

    questions = [
        line.strip()
        for line in str(row["questions_list"] or "").splitlines()
        if line.strip()
    ]
    if not questions:
        return None

    distribution = analyze_topic_distribution(questions)
    transition = analyze_topic_transition(questions)
    unknown_count = sum(1 for question in questions if _is_unknown_question(question))
    confidence = max(0.0, 1.0 - (unknown_count / len(questions)))
    recommended_order = sorted(
        distribution,
        key=lambda phase: distribution[phase],
        reverse=True,
    )

    return {
        "source": "experience",
        "experience_id": int(row["id"]),
        "distribution": distribution,
        "transition": transition,
        "recommended_order": recommended_order,
        "confidence": confidence,
        "unknown_count": unknown_count,
    }


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _is_unknown_question(question: str) -> bool:
    text = (question or "").strip()
    return bool(text) and not any(pattern.search(text) for _, pattern in _PHASE_PATTERNS)

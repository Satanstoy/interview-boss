"""Canonical interview-question types and distribution facts.

This module is the single vocabulary shared by storage, statistics, and the
mock-interview controller.  It deliberately keeps classification deterministic
so that a historical backfill and a future write produce the same fact.
"""

from __future__ import annotations

from enum import Enum
import re
from statistics import median, pstdev
from typing import Iterable
import uuid

from app.core.interview_distribution_config import derive_job_family, positions_for_family


class QuestionType(str, Enum):
    PROJECT_FOLLOWUP = "project_followup"
    KNOWLEDGE_PROBE = "knowledge_probe"
    ALGORITHM_CODING = "algorithm_coding"
    SYSTEM_DESIGN = "system_design"
    BEHAVIORAL = "behavioral"
    UNCLASSIFIED = "unclassified"


QUESTION_TYPES = tuple(
    question_type
    for question_type in QuestionType
    if question_type is not QuestionType.UNCLASSIFIED
)

MIN_EFFECTIVE_PRIMARY_QUESTIONS = 5
MAX_UNCLASSIFIED_RATIO = 0.20
DEFAULT_TOTAL_QUESTION_COUNT = 10
PRIOR_STRENGTH = 5.0
SYSTEM_BASELINE_SCOPE = "system_baseline"
JOB_FAMILY_SCOPE = "job_family"
PUBLIC_POSITION_SCOPE = "public_job_position"
SYSTEM_BASELINE_KEY = "__system__"
BEHAVIORAL_SIGNAL_TERMS = (
    "人力资源",
    "行为面",
    "软技能",
    "冲突",
    "协作",
    "失败",
    "复盘",
    "star",
    "职业规划",
    "影响力",
)
BEHAVIORAL_ACRONYM_TERMS = ("hr",)
_BEHAVIORAL_SIGNAL_RE = re.compile(
    "|".join(re.escape(term) for term in BEHAVIORAL_SIGNAL_TERMS), re.I
)
_BEHAVIORAL_ACRONYM_RE = re.compile(
    "|".join(rf"(?<![a-z]){re.escape(term)}(?![a-z])" for term in BEHAVIORAL_ACRONYM_TERMS),
    re.I,
)


class DistributionStatsUnavailable(RuntimeError):
    """Raised when no complete materialized distribution is available."""


def _combined_text(cat1: str | None, cat2: str | None, tags: str | None, question: str | None) -> str:
    return " ".join(value or "" for value in (cat1, cat2, tags, question)).lower()


def map_question_type(
    cat1: str | None,
    cat2: str | None,
    tags: str | None,
    question: str | None,
) -> QuestionType:
    """Map existing taxonomy values to one canonical mock-interview type."""
    text = _combined_text(cat1, cat2, tags, question)
    if not text:
        return QuestionType.UNCLASSIFIED

    if re.search(r"(^|\s)e\.|算法|数据结构|手撕|leetcode|动态规划|二分", text, re.I):
        return QuestionType.ALGORITHM_CODING
    if _BEHAVIORAL_SIGNAL_RE.search(text) or _BEHAVIORAL_ACRONYM_RE.search(text):
        return QuestionType.BEHAVIORAL
    if re.search(r"系统设计|架构设计|高可用|扩展性|分布式|限流|降级|容灾", text, re.I):
        return QuestionType.SYSTEM_DESIGN
    if re.search(r"(^|\s)a\.|项目经验|项目介绍|难点攻关|项目复盘|负责过的项目", text, re.I):
        return QuestionType.PROJECT_FOLLOWUP
    if re.search(r"(^|\s)[bcd]\.|基础|原理|中间件|数据库|操作系统|网络|agent|rag|prompt", text, re.I):
        return QuestionType.KNOWLEDGE_PROBE
    return QuestionType.UNCLASSIFIED


def map_dimension(question_type: QuestionType | str) -> str:
    """Return the reporting-only high-level dimension for a canonical type."""
    value = QuestionType(question_type)
    if value is QuestionType.PROJECT_FOLLOWUP:
        return "project_deep_dive"
    if value is QuestionType.BEHAVIORAL:
        return "behavioral"
    if value is QuestionType.UNCLASSIFIED:
        return "unclassified"
    return "knowledge_probe"


def _empty_counts() -> dict[str, int]:
    return {question_type.value: 0 for question_type in QUESTION_TYPES}


def _uniform_distribution() -> dict[str, float]:
    ratio = 1.0 / len(QUESTION_TYPES)
    return {question_type.value: ratio for question_type in QUESTION_TYPES}


def mark_distribution_refresh(cursor, job_position: str, scope: str = PUBLIC_POSITION_SCOPE) -> None:
    """Coalesce a stale-statistics request for one public position/scope."""
    cursor.execute(
        """
        INSERT INTO interview_distribution_refresh_jobs (
            scope, job_position, requested_source_version, status, updated_at
        ) VALUES (?, ?, CAST(strftime('%s', 'now') AS TEXT), 'pending', CURRENT_TIMESTAMP)
        ON CONFLICT(scope, job_position) DO UPDATE SET
            requested_source_version = excluded.requested_source_version,
            status = 'pending',
            last_error = NULL,
            next_retry_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        """,
        (scope, job_position),
    )


def _public_details(conn) -> list[dict]:
    """Load phase-one facts, including unclassified details for quality gates."""
    rows = conn.execute(
        """
        SELECT i.id AS interview_id, i.job_position, qd.question_type
        FROM interview i
        JOIN questions_detail qd ON qd.interview_id = i.id
        WHERE i.owner_id IS NULL
          AND i.status = 'approved'
          AND i.deleted_at IS NULL
          AND qd.deleted_at IS NULL
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _details_for_positions(rows: Iterable[dict], positions: set[str] | None) -> list[dict]:
    if positions is None:
        return list(rows)
    return [row for row in rows if row["job_position"] in positions]


def _accepted_interviews(rows: Iterable[dict]) -> tuple[dict[int, list[str]], dict[int, str]]:
    """Apply quality gates before the typed phase-two aggregation."""
    grouped: dict[int, list[str]] = {}
    for row in rows:
        grouped.setdefault(row["interview_id"], []).append(row["question_type"] or "unclassified")

    accepted: dict[int, list[str]] = {}
    exclusions: dict[int, str] = {}
    valid_types = {item.value for item in QUESTION_TYPES}
    for interview_id, types in grouped.items():
        effective = [question_type for question_type in types if question_type in valid_types]
        unclassified_count = len(types) - len(effective)
        if len(effective) < MIN_EFFECTIVE_PRIMARY_QUESTIONS:
            exclusions[interview_id] = "too_few_effective_questions"
            continue
        if unclassified_count / len(types) > MAX_UNCLASSIFIED_RATIO:
            exclusions[interview_id] = "unclassified_ratio_exceeded"
            continue
        accepted[interview_id] = effective
    return accepted, exclusions


def _confidence(sample_count: int) -> str:
    if sample_count >= 20:
        return "high"
    if sample_count >= 5:
        return "medium"
    return "low"


def _next_stats_version(conn, scope: str, job_position: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(stats_version), 0) AS version "
        "FROM interview_distribution_stats WHERE scope = ? AND job_position = ?",
        (scope, job_position),
    ).fetchone()
    return int(row["version"]) + 1


def _publish_scope(
    conn,
    *,
    scope: str,
    job_position: str,
    parent_scope: str | None,
    parent_job_position: str | None,
    parent_ratio: dict[str, float],
    accepted: dict[int, list[str]],
    exclusions: dict[int, str],
) -> dict:
    raw_counts = _empty_counts()
    effective_counts: list[int] = []
    for types in accepted.values():
        effective_counts.append(len(types))
        for question_type in types:
            raw_counts[question_type] += 1

    posterior_alpha = {
        question_type: raw_counts[question_type] + PRIOR_STRENGTH * parent_ratio[question_type]
        for question_type in raw_counts
    }
    alpha_total = sum(posterior_alpha.values())
    ratios = {
        question_type: posterior_alpha[question_type] / alpha_total
        for question_type in posterior_alpha
    }
    version = _next_stats_version(conn, scope, job_position)
    sample_count = len(accepted)
    sample_questions = sum(effective_counts)
    recommended_total_count = (
        int(median(effective_counts)) if effective_counts else DEFAULT_TOTAL_QUESTION_COUNT
    )
    dispersion = float(pstdev(effective_counts)) if len(effective_counts) > 1 else 0.0
    confidence = _confidence(sample_count)

    for question_type in raw_counts:
        conn.execute(
            """
            INSERT INTO interview_distribution_stats (
                scope, job_position, question_type, stats_version, posterior_mean_ratio,
                posterior_alpha, raw_question_count, sample_interview_count,
                sample_question_count, recommended_total_count, dispersion, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope,
                job_position,
                question_type,
                version,
                ratios[question_type],
                posterior_alpha[question_type],
                raw_counts[question_type],
                sample_count,
                sample_questions,
                recommended_total_count,
                dispersion,
                confidence,
            ),
        )
    for interview_id, reason in exclusions.items():
        conn.execute(
            """
            INSERT INTO interview_distribution_stat_exclusions (
                stats_version, scope, job_position, interview_id, exclusion_reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (version, scope, job_position, interview_id, reason),
        )

    return {
        "scope": scope,
        "job_position": job_position,
        "stats_version": version,
        "parent_scope": parent_scope,
        "parent_job_position": parent_job_position,
        "raw_counts": raw_counts,
        "posterior_mean_ratio": ratios,
        "sample_interview_count": sample_count,
        "sample_question_count": sample_questions,
        "recommended_total_count": recommended_total_count,
        "dispersion": dispersion,
        "confidence": confidence,
    }


def refresh_distribution_scope(conn, scope: str, job_position: str) -> dict:
    """Materialize a complete hierarchy then return the requested scope.

    The first phase includes unclassified details to enforce quality gates.  The
    second phase aggregates only accepted canonical question types.
    """
    if scope not in {SYSTEM_BASELINE_SCOPE, JOB_FAMILY_SCOPE, PUBLIC_POSITION_SCOPE}:
        raise ValueError(f"Unsupported distribution scope: {scope}")

    all_rows = _public_details(conn)
    system_accepted, system_exclusions = _accepted_interviews(all_rows)
    system_result = _publish_scope(
        conn,
        scope=SYSTEM_BASELINE_SCOPE,
        job_position=SYSTEM_BASELINE_KEY,
        parent_scope=None,
        parent_job_position=None,
        parent_ratio=_uniform_distribution(),
        accepted=system_accepted,
        exclusions=system_exclusions,
    )

    family = derive_job_family(job_position)
    family_rows = _details_for_positions(all_rows, set(positions_for_family(family)))
    family_accepted, family_exclusions = _accepted_interviews(family_rows)
    family_result = _publish_scope(
        conn,
        scope=JOB_FAMILY_SCOPE,
        job_position=family,
        parent_scope=SYSTEM_BASELINE_SCOPE,
        parent_job_position=SYSTEM_BASELINE_KEY,
        parent_ratio=system_result["posterior_mean_ratio"],
        accepted=family_accepted,
        exclusions=family_exclusions,
    )

    position_rows = _details_for_positions(all_rows, {job_position})
    position_accepted, position_exclusions = _accepted_interviews(position_rows)
    position_result = _publish_scope(
        conn,
        scope=PUBLIC_POSITION_SCOPE,
        job_position=job_position,
        parent_scope=JOB_FAMILY_SCOPE,
        parent_job_position=family,
        parent_ratio=family_result["posterior_mean_ratio"],
        accepted=position_accepted,
        exclusions=position_exclusions,
    )

    requested = {
        SYSTEM_BASELINE_SCOPE: system_result,
        JOB_FAMILY_SCOPE: family_result,
        PUBLIC_POSITION_SCOPE: position_result,
    }[scope]
    mark_distribution_refresh(conn.cursor(), job_position, scope)
    conn.execute(
        """
        UPDATE interview_distribution_refresh_jobs
        SET published_source_version = ?, status = 'completed', updated_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND job_position = ?
        """,
        (str(requested["stats_version"]), scope, job_position),
    )
    return requested


def _complete_stats_rows(conn, scope: str, job_position: str):
    rows = conn.execute(
        """
        SELECT * FROM interview_distribution_stats
        WHERE scope = ? AND job_position = ?
          AND stats_version = (
              SELECT MAX(stats_version) FROM interview_distribution_stats
              WHERE scope = ? AND job_position = ?
          )
        ORDER BY question_type
        """,
        (scope, job_position, scope, job_position),
    ).fetchall()
    if len(rows) != len(QUESTION_TYPES):
        return None
    if {row["question_type"] for row in rows} != {item.value for item in QUESTION_TYPES}:
        return None
    return rows


def get_distribution_default(conn, job_position: str) -> dict:
    """Read the latest complete default with position/family/system fallback."""
    family = derive_job_family(job_position)
    candidates = (
        (PUBLIC_POSITION_SCOPE, job_position),
        (JOB_FAMILY_SCOPE, family),
        (SYSTEM_BASELINE_SCOPE, SYSTEM_BASELINE_KEY),
    )
    for scope, key in candidates:
        rows = _complete_stats_rows(conn, scope, key)
        if rows is None:
            continue
        first = rows[0]
        return {
            "scope": scope,
            "job_position": key,
            "stats_version": first["stats_version"],
            "distribution": {row["question_type"]: row["posterior_mean_ratio"] for row in rows},
            "raw_counts": {row["question_type"]: row["raw_question_count"] for row in rows},
            "recommended_total_count": first["recommended_total_count"],
            "sample_interview_count": first["sample_interview_count"],
            "sample_question_count": first["sample_question_count"],
            "dispersion": first["dispersion"],
            "confidence": first["confidence"],
        }
    raise DistributionStatsUnavailable(f"No complete interview distribution stats for {job_position}")


def _largest_remainder_counts(distribution: dict[str, float], total: int) -> dict[str, int]:
    exact = {key: distribution[key] * total for key in distribution}
    counts = {key: int(value) for key, value in exact.items()}
    for key in sorted(distribution, key=lambda item: (exact[item] - counts[item], item), reverse=True)[: total - sum(counts.values())]:
        counts[key] += 1
    return counts


def compile_distribution_plan(
    conn,
    *,
    user_id: int,
    job_position: str,
    request_override: dict | None,
    preference: dict | None,
) -> dict:
    """Freeze the exact values used by one mock-interview session."""
    source = request_override or preference or {"mode": "system_default"}
    default = get_distribution_default(conn, job_position)
    mode = source.get("mode", "system_default")
    distribution = default["distribution"]
    if mode == "custom":
        distribution = source["custom_distribution"]
    target = int(source.get("target_question_count") or default["recommended_total_count"])
    soft_targets = _largest_remainder_counts(distribution, target)
    return {
        "plan_id": str(uuid.uuid4()),
        "stats_version": default["stats_version"],
        "source_scope": default["scope"],
        "mode": mode,
        "target_question_count": target,
        "distribution": distribution,
        "expected_distribution": distribution,
        "soft_target_counts": soft_targets,
        "allowed_counts": {
            key: {"min": 0, "max": target} for key in distribution
        },
        "random_seed": str(uuid.uuid4()),
        "style_source_snapshot": None,
    }

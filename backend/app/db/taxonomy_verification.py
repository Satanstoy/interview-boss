"""Read-only checks for the taxonomy 1.1 rollout."""

from __future__ import annotations

from app.core.interview_distribution_config import derive_job_family
from app.core.taxonomy import DEFAULT_TAXONOMY, TAXONOMY_VERSION, taxonomy_for_position


def _scalar(conn, query: str, params: tuple = (), default=0):
    row = conn.execute(query, params).fetchone()
    return row[0] if row and row[0] is not None else default


def select_agent_question_ids_without_answers(
    conn, owner_id: int | None = None
) -> list[int]:
    """Return active Agent questions that need a real reference answer.

    When ``owner_id`` is provided, return only public questions and that
    owner's private questions, matching the API visibility contract.
    """

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    deleted_column = ", deleted_at" if "deleted_at" in columns else ""
    rows = conn.execute(
        "SELECT id, owner_id, job_position, ai_answer"
        + deleted_column
        + " FROM question_bank"
    ).fetchall()
    result = []
    for row in rows:
        if derive_job_family(row["job_position"]) != "agent_llm":
            continue
        if owner_id is not None and row["owner_id"] not in (None, owner_id):
            continue
        if deleted_column and row["deleted_at"] is not None:
            continue
        answer = str(row["ai_answer"] or "").strip()
        if not answer or "生成失败" in answer:
            result.append(int(row["id"]))
    return sorted(result)


def inspect_taxonomy_v11(conn) -> dict[str, int | str]:
    """Return migration health counters without changing the database."""

    schema_version = int(
        _scalar(conn, "SELECT COALESCE(MAX(version), 0) FROM schema_version")
    )
    system_taxonomy_count = int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM taxonomy WHERE source = 'system' AND owner_id IS NULL "
            "AND version = ?",
            (TAXONOMY_VERSION,),
        )
    )
    question_count = int(_scalar(conn, "SELECT COUNT(*) FROM question_bank"))
    answer_refresh_required = int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM question_bank "
            "WHERE ai_answer IS NOT NULL AND TRIM(ai_answer) != '' "
            "AND ai_answer NOT LIKE '%生成失败%' "
            "AND COALESCE(answer_taxonomy_version, '') != ?",
            (TAXONOMY_VERSION,),
        )
    )
    audit_count = int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM taxonomy_migration_audit "
            "WHERE migration_version IN (?, '1.1-agent-manual')",
            (TAXONOMY_VERSION,),
        )
    )
    manual_agent_correction_count = int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM taxonomy_migration_audit "
            "WHERE migration_version = '1.1-agent-manual'",
        )
    )

    invalid_category_count = 0
    rows = conn.execute(
        "SELECT cat1, cat2, job_position FROM question_bank"
    ).fetchall()
    for row in rows:
        position = row["job_position"] or DEFAULT_TAXONOMY["job_position"]
        known_pairs = {
            (category.get("cat1", ""), child)
            for category in taxonomy_for_position(position).get("categories", [])
            for child in category.get("children", [])
        }
        if (row["cat1"] or "", row["cat2"] or "") not in known_pairs:
            invalid_category_count += 1

    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "schema_version": schema_version,
        "system_taxonomy_count": system_taxonomy_count,
        "question_count": question_count,
        "answer_refresh_required": answer_refresh_required,
        "invalid_category_count": invalid_category_count,
        "migration_audit_count": audit_count,
        "manual_agent_correction_count": manual_agent_correction_count,
    }

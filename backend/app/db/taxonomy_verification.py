"""Read-only checks for the taxonomy 1.1 rollout."""

from __future__ import annotations

from app.core.taxonomy import TAXONOMY_VERSION, taxonomy_for_position


def _scalar(conn, query: str, params: tuple = (), default=0):
    row = conn.execute(query, params).fetchone()
    return row[0] if row and row[0] is not None else default


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
            "SELECT COUNT(*) FROM taxonomy_migration_audit WHERE migration_version = ?",
            (TAXONOMY_VERSION,),
        )
    )

    invalid_category_count = 0
    rows = conn.execute(
        "SELECT cat1, cat2, job_position FROM question_bank"
    ).fetchall()
    for row in rows:
        known_pairs = {
            (category.get("cat1", ""), child)
            for category in taxonomy_for_position(row["job_position"]).get("categories", [])
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
    }

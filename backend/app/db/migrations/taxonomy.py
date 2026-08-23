"""Taxonomy 1.1 schema and data migration."""

from __future__ import annotations

import json
import logging

from app.core.taxonomy import (
    DEFAULT_TAXONOMY,
    TAXONOMY_VERSION,
    map_legacy_category,
    taxonomy_for_position,
)

logger = logging.getLogger("interview-boss")


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _known_category_pairs(position: str | None) -> set[tuple[str, str]]:
    taxonomy = taxonomy_for_position(position)
    return {
        (category.get("cat1", ""), child)
        for category in taxonomy.get("categories", [])
        for child in category.get("children", [])
    }


def _map_row_category(
    cat1: str | None,
    cat2: str | None,
    question: str | None,
    position: str | None,
) -> tuple[str, str, str]:
    pair = (str(cat1 or "").strip(), str(cat2 or "").strip())
    if pair in _known_category_pairs(position):
        return pair[0], pair[1], "already_taxonomy_v11"
    return map_legacy_category(cat1, cat2, question, position)


def _position_names(conn) -> list[str]:
    names: set[str] = {DEFAULT_TAXONOMY["job_position"]}
    position_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('job_positions')").fetchall()
    }
    active_position_filter = ""
    if "is_deleted" in position_columns:
        active_position_filter = " AND (is_deleted = 0 OR is_deleted IS NULL)"
    queries = (
        "SELECT name FROM job_positions WHERE name IS NOT NULL AND TRIM(name) != ''"
        + active_position_filter,
        "SELECT job_position FROM question_bank WHERE job_position IS NOT NULL AND TRIM(job_position) != ''",
        "SELECT job_position FROM questions_detail WHERE job_position IS NOT NULL AND TRIM(job_position) != ''",
        "SELECT value FROM user_profile WHERE key = 'current_job_position'",
    )
    for query in queries:
        try:
            names.update(str(row[0]).strip() for row in conn.execute(query).fetchall() if row[0])
        except Exception:
            # A partially initialized test database may not have every optional
            # table yet. The migration still seeds the default taxonomy.
            continue
    return sorted(name for name in names if name)


def _seed_system_taxonomies(conn) -> int:
    seeded = 0
    for position in _position_names(conn):
        config = taxonomy_for_position(position)
        categories_json = json.dumps(config["categories"], ensure_ascii=False)
        existing = conn.execute(
            "SELECT id FROM taxonomy WHERE position_name = ? AND source = 'system' "
            "AND owner_id IS NULL ORDER BY id LIMIT 1",
            (position,),
        ).fetchone()
        is_default = int(position == DEFAULT_TAXONOMY["job_position"])
        if existing:
            conn.execute(
                "UPDATE taxonomy SET categories_json = ?, version = ?, is_default = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (categories_json, TAXONOMY_VERSION, is_default, existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO taxonomy "
                "(position_name, categories_json, version, is_default, source, owner_id, is_public) "
                "VALUES (?, ?, ?, ?, 'system', NULL, 0)",
                (position, categories_json, TAXONOMY_VERSION, is_default),
            )
            seeded += 1
    return seeded


def _migrate_question_table(conn, table: str, has_answer: bool) -> tuple[int, int]:
    columns = "id, question, cat1, cat2, job_position"
    if has_answer:
        columns += ", ai_answer"
    rows = conn.execute(f"SELECT {columns} FROM {table}").fetchall()
    changed = 0
    stale_answers = 0
    for row in rows:
        position = row["job_position"] or DEFAULT_TAXONOMY["job_position"]
        new_cat1, new_cat2, reason = _map_row_category(
            row["cat1"], row["cat2"], row["question"], position
        )
        old_pair = (row["cat1"] or "", row["cat2"] or "")
        category_changed = old_pair != (new_cat1, new_cat2)
        if category_changed or reason != "already_taxonomy_v11":
            changed += 1
            conn.execute(
                f"UPDATE {table} SET cat1 = ?, cat2 = ?, taxonomy_version = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_cat1, new_cat2, TAXONOMY_VERSION, row["id"]),
            )
            conn.execute(
                "INSERT INTO taxonomy_migration_audit "
                "(migration_version, table_name, record_id, old_cat1, old_cat2, "
                "new_cat1, new_cat2, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(migration_version, table_name, record_id) DO UPDATE SET "
                "old_cat1 = excluded.old_cat1, old_cat2 = excluded.old_cat2, "
                "new_cat1 = excluded.new_cat1, new_cat2 = excluded.new_cat2, "
                "reason = excluded.reason",
                (
                    TAXONOMY_VERSION,
                    table,
                    row["id"],
                    row["cat1"] or "",
                    row["cat2"] or "",
                    new_cat1,
                    new_cat2,
                    reason,
                ),
            )
        else:
            conn.execute(
                f"UPDATE {table} SET taxonomy_version = ? WHERE id = ?",
                (TAXONOMY_VERSION, row["id"]),
            )

        if has_answer and row["ai_answer"] and str(row["ai_answer"]).strip() and "生成失败" not in row["ai_answer"]:
            conn.execute(
                "UPDATE question_bank SET answer_taxonomy_version = NULL WHERE id = ?",
                (row["id"],),
            )
            stale_answers += 1
    return changed, stale_answers


def _migration_106_taxonomy_v11(conn):
    """Upgrade taxonomy labels to 1.1 without calling an external API.

    This function is registered in ``run_migrations``. Production deployment
    runs it transactionally during startup/deploy, after the automatic backup
    for destructive version 106 has been created. Version 106 is intentional:
    production already uses migration versions 102-105 for other changes.
    """
    _add_column_if_missing(conn, "taxonomy", "version", f"TEXT NOT NULL DEFAULT '{TAXONOMY_VERSION}'")
    # Personal taxonomies are user-owned extensions, not the system taxonomy
    # release. Keep them explicitly custom so they are not presented as a
    # frozen 1.1 system taxonomy after the column backfill.
    conn.execute("UPDATE taxonomy SET version = 'custom' WHERE source = 'user'")
    _add_column_if_missing(conn, "question_bank", "taxonomy_version", f"TEXT NOT NULL DEFAULT '{TAXONOMY_VERSION}'")
    _add_column_if_missing(conn, "question_bank", "answer_taxonomy_version", "TEXT")
    _add_column_if_missing(conn, "questions_detail", "taxonomy_version", f"TEXT NOT NULL DEFAULT '{TAXONOMY_VERSION}'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS taxonomy_migration_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_version TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            old_cat1 TEXT NOT NULL DEFAULT '',
            old_cat2 TEXT NOT NULL DEFAULT '',
            new_cat1 TEXT NOT NULL DEFAULT '',
            new_cat2 TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(migration_version, table_name, record_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_taxonomy_migration_audit_version "
        "ON taxonomy_migration_audit(migration_version, table_name)"
    )

    seeded = _seed_system_taxonomies(conn)
    qb_changed, stale_answers = _migrate_question_table(conn, "question_bank", True)
    qd_changed, _ = _migrate_question_table(conn, "questions_detail", False)
    logger.info(
        "migration_106: taxonomy %s 完成，system_taxonomies=%s, "
        "question_bank_changed=%s, questions_detail_changed=%s, stale_answers=%s",
        TAXONOMY_VERSION,
        seeded,
        qb_changed,
        qd_changed,
        stale_answers,
    )

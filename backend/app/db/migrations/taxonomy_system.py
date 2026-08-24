"""System taxonomy seed migration (104)."""

import json
import logging

from app.core.system_taxonomies import SYSTEM_TAXONOMIES

logger = logging.getLogger("interview-boss")


def _migration_104_system_taxonomies(conn):
    """Store canonical cat1/cat2/tags without touching user history.

    Only active rows in ``job_positions`` receive a taxonomy.  Agent keeps its
    historical categories for compatibility; the other built-in positions are
    seeded from the checked-in canonical definitions.
    """
    taxonomy_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('taxonomy')").fetchall()
    }
    if "tags_json" not in taxonomy_columns:
        conn.execute("ALTER TABLE taxonomy ADD COLUMN tags_json TEXT DEFAULT '[]'")

    position_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('job_positions')").fetchall()
    }
    deleted_filter = "AND (is_deleted = 0 OR is_deleted IS NULL)" if "is_deleted" in position_columns else ""
    rows = conn.execute(
        f"SELECT name FROM job_positions WHERE name IN ({','.join('?' for _ in SYSTEM_TAXONOMIES)}) {deleted_filter}",
        tuple(SYSTEM_TAXONOMIES),
    ).fetchall()

    for row in rows:
        position = row[0]
        config = SYSTEM_TAXONOMIES[position]
        categories_json = json.dumps(config["categories"], ensure_ascii=False)
        tags_json = json.dumps(config["tags"], ensure_ascii=False)
        existing = conn.execute(
            "SELECT id FROM taxonomy WHERE position_name = ? AND source = 'system' AND owner_id IS NULL",
            (position,),
        ).fetchone()
        if existing:
            if position == "agent开发/大模型应用开发/大模型开发":
                conn.execute(
                    "UPDATE taxonomy SET tags_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (tags_json, existing[0]),
                )
            else:
                conn.execute(
                    "UPDATE taxonomy SET categories_json = ?, tags_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (categories_json, tags_json, existing[0]),
                )
        else:
            conn.execute(
                "INSERT INTO taxonomy "
                "(position_name, categories_json, tags_json, source, owner_id, is_default, is_public) "
                "VALUES (?, ?, ?, 'system', NULL, 0, 0)",
                (position, categories_json, tags_json),
            )
    logger.info("migration_104: system taxonomies seeded for %d active positions", len(rows))

"""Project-level Harness provenance tables (migration 101)."""

from __future__ import annotations


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migration_101_project_harness_releases(conn):
    """Persist the application's Harness identity outside Eval manifests."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS harness_releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            harness_key TEXT NOT NULL,
            target_type TEXT NOT NULL,
            version TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published', 'archived')),
            manifest_json TEXT NOT NULL,
            manifest_digest TEXT NOT NULL,
            source_ref TEXT NOT NULL DEFAULT '',
            git_sha TEXT NOT NULL DEFAULT '',
            image_digest TEXT NOT NULL DEFAULT '',
            config_digest TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            published_at TIMESTAMP,
            archived_at TIMESTAMP,
            UNIQUE(harness_key, version)
        );

        CREATE INDEX IF NOT EXISTS idx_harness_releases_target_status
            ON harness_releases(target_type, status, id DESC);

        INSERT OR IGNORE INTO harness_releases (
            harness_key, target_type, version, display_name, status,
            manifest_json, manifest_digest, source_ref, git_sha,
            image_digest, config_digest, published_at
        )
        SELECT
            substr(r.release_key, 1, instr(r.release_key, '@') - 1),
            r.target_type,
            r.version,
            r.display_name,
            r.status,
            r.manifest_json,
            r.manifest_digest,
            'legacy_eval_release',
            r.git_sha,
            r.image_digest,
            r.config_digest,
            r.published_at
        FROM eval_releases r
        WHERE r.release_type = 'simulator_harness';
        """
    )
    _add_column_if_missing(
        conn,
        "eval_batches",
        "harness_release_id",
        "INTEGER REFERENCES harness_releases(id) ON DELETE RESTRICT",
    )
    _add_column_if_missing(
        conn,
        "eval_runs",
        "harness_release_id",
        "INTEGER REFERENCES harness_releases(id) ON DELETE RESTRICT",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_batches_harness_release "
        "ON eval_batches(harness_release_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_runs_harness_release "
        "ON eval_runs(harness_release_id, created_at DESC)"
    )
    conn.execute(
        """
        UPDATE eval_batches
        SET harness_release_id = (
            SELECT h.id
            FROM harness_releases h
            JOIN eval_releases r ON r.release_key = h.harness_key || '@' || h.version
            WHERE r.id = eval_batches.simulator_harness_release_id
        )
        WHERE harness_release_id IS NULL
        """
    )
    conn.execute(
        """
        UPDATE eval_runs
        SET harness_release_id = (
            SELECT h.id
            FROM harness_releases h
            JOIN eval_releases r ON r.release_key = h.harness_key || '@' || h.version
            WHERE r.id = eval_runs.simulator_harness_release_id
        )
        WHERE harness_release_id IS NULL
        """
    )

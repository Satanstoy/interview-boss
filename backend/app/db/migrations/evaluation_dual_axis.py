"""Evaluation dual-axis schema additions (migration 093)."""

from __future__ import annotations


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    columns = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migration_093_evaluation_dual_axis(conn):
    """Add the Evaluation Release binding and immutable run snapshot columns.

    The legacy component foreign-key columns remain temporarily for historical
    rows and old readers. New runs use ``evaluation_release_id`` and the
    snapshot as their source of truth.
    """
    _add_column_if_missing(
        conn,
        "eval_batches",
        "evaluation_release_id",
        "INTEGER REFERENCES eval_releases(id) ON DELETE RESTRICT",
    )
    _add_column_if_missing(
        conn,
        "eval_batches",
        "snapshot_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        conn,
        "eval_runs",
        "evaluation_release_id",
        "INTEGER REFERENCES eval_releases(id) ON DELETE RESTRICT",
    )
    _add_column_if_missing(
        conn,
        "eval_runs",
        "snapshot_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_batches_evaluation_release "
        "ON eval_batches(evaluation_release_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_runs_evaluation_release "
        "ON eval_runs(evaluation_release_id, created_at DESC)"
    )

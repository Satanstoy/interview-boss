#!/usr/bin/env python3
"""Generate and verify the SQLite schema reference from the migration registry."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUTPUT = ROOT / "docs" / "architecture" / "schema.md"
sys.path.insert(0, str(BACKEND))


def _bootstrap_legacy_tables(conn: sqlite3.Connection) -> None:
    """Create the two legacy tables required before migration 004 can run."""
    conn.execute(
        """
        CREATE TABLE jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, company TEXT,
            season TEXT DEFAULT '', owner_id INTEGER, status TEXT DEFAULT 'approved',
            url_signature TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            job_position TEXT DEFAULT '', deleted_at TIMESTAMP, tech_stack TEXT,
            source TEXT DEFAULT '', position TEXT DEFAULT '', salary TEXT DEFAULT '',
            job_title TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT, interview_id INTEGER,
            question TEXT, cat1 TEXT, cat2 TEXT, tags TEXT, difficulty TEXT,
            diff_tag TEXT, answer TEXT, url TEXT, source TEXT DEFAULT '',
            owner_id INTEGER, status TEXT DEFAULT 'approved', deleted_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, company TEXT DEFAULT '',
            round TEXT DEFAULT '', job_position TEXT DEFAULT ''
        )
        """
    )


def _fresh_schema() -> sqlite3.Connection:
    os.environ.setdefault("ADMIN_PASSWORD", "schema-doc-ci-placeholder")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _bootstrap_legacy_tables(conn)

    from app.db.migrations import run_migrations

    run_migrations(conn)
    return conn


def _source_commit() -> str:
    configured = os.environ.get("SCHEMA_SOURCE_MIGRATION_COMMIT", "").strip()
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--format=%h", "--", "backend/app/db/migrations"],
            cwd=ROOT,
            text=True,
        ).strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'question_fts_%' "
        "ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def _table_section(conn: sqlite3.Connection, table: str) -> list[str]:
    lines = [f"### `{table}`"]
    columns = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    lines.append(
        "- Columns: "
        + ", ".join(f"`{row[1]}`:{row[2] or 'ANY'}" for row in columns)
    )

    foreign_keys = conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
    if foreign_keys:
        lines.append(
            "- Foreign keys: "
            + "; ".join(
                f"`{row[3]}` -> `{row[2]}`.`{row[4]}` ({row[6]})"
                for row in foreign_keys
            )
        )
    else:
        lines.append("- Foreign keys: none")

    indexes = []
    for index in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
        name = index[1]
        unique = " UNIQUE" if index[2] else ""
        partial = " partial" if len(index) > 4 and index[4] else ""
        fields = conn.execute(f'PRAGMA index_info("{name}")').fetchall()
        indexes.append(
            f"`{name}`{unique}{partial} ("
            + ", ".join(row[2] or f"expr:{row[1]}" for row in fields)
            + ")"
        )
    lines.append("- Indexes: " + ("; ".join(sorted(indexes)) if indexes else "none"))
    lines.append("")
    return lines


def build_document() -> str:
    from app.db.migrations import _MIGRATIONS

    conn = _fresh_schema()
    try:
        migrations = conn.execute(
            "SELECT version, name, applied_at FROM schema_version ORDER BY version"
        ).fetchall()
        latest_version, latest_name, _ = _MIGRATIONS[-1]
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = _table_names(conn)

        lines = [
            "# InterviewBoss SQLite Schema",
            "",
            f"> Generated: {dt.date.today().isoformat()}",
            f"> Source migration commit: {_source_commit()}",
            f"> Latest migration: {latest_version} ({latest_name})",
            f"> foreign_key_check: {len(fk_errors)}",
            "> Source of truth: `backend/app/db/migrations/` applied to a fresh in-memory SQLite database.",
            "> Runtime: SQLite WAL with `PRAGMA foreign_keys=ON`; soft-deleted rows use `deleted_at IS NULL` filters where documented by the owning service.",
            "",
            "## Migration history",
            "",
        ]
        lines.extend(
            [
                "| Version | Name | Applied in fresh schema |",
                "|---:|---|---|",
            ]
        )
        lines.extend(f"| {row[0]} | `{row[1]}` | yes |" for row in migrations)
        lines.extend(["", f"## Tables ({len(tables)})", ""])
        for table in tables:
            lines.extend(_table_section(conn, table))
        return "\n".join(lines).rstrip() + "\n"
    finally:
        conn.close()


def _normalise_generated_metadata(value: str) -> str:
    value = re.sub(r"^> Generated: .*?$", "> Generated: <date>", value, flags=re.MULTILINE)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when the committed doc is stale")
    args = parser.parse_args()
    expected = build_document()
    if args.check:
        actual = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if _normalise_generated_metadata(actual) != _normalise_generated_metadata(expected):
            print(f"schema docs are stale: regenerate {OUTPUT}", file=sys.stderr)
            return 1
        print("schema docs are fresh")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

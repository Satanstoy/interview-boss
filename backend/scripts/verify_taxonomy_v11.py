#!/usr/bin/env python3
"""Read-only production verification for database taxonomy migration 102.

Examples:
    uv run python backend/scripts/verify_taxonomy_v11.py
    uv run python backend/scripts/verify_taxonomy_v11.py --db-path /path/to/interview-boss.db --json

The command only opens SQLite and runs SELECTs. It never invokes an LLM and
never writes to the database.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.core.config import DB_PATH
from app.db.taxonomy_verification import inspect_taxonomy_v11


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=DB_PATH, help="SQLite database path")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        report = inspect_taxonomy_v11(conn)
    finally:
        conn.close()

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")

    return 0 if report["schema_version"] >= 102 else 1


if __name__ == "__main__":
    raise SystemExit(main())

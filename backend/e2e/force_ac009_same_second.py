"""Fix both accepted roots to the same server timestamp before workers start."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] == sys.argv[2]:
        raise SystemExit("expected two distinct upload import IDs")
    import_ids = sys.argv[1:]
    fixed_timestamp = "2026-10-04 12:00:00"
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, requester_id, status, created_at FROM upload_imports "
            "WHERE id IN (?, ?) ORDER BY id",
            import_ids,
        ).fetchall()
        if len(rows) != 2:
            raise AssertionError(f"expected both accepted imports, got {len(rows)}")
        conn.execute(
            "UPDATE upload_imports SET created_at = ? WHERE id IN (?, ?)",
            (fixed_timestamp, *import_ids),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT id, requester_id, status, created_at FROM upload_imports "
            "WHERE id IN (?, ?) ORDER BY id",
            import_ids,
        ).fetchall()
        if any(row["created_at"] != fixed_timestamp for row in updated):
            raise AssertionError("the two roots do not share the fixed timestamp")
        print(
            json.dumps(
                {
                    "fixed_timestamp": fixed_timestamp,
                    "roots": [dict(row) for row in updated],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()

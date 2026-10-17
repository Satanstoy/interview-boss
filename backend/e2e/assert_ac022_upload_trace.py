"""Assert the final AC-022 rows in the disposable real-stack database."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


def main() -> None:
    idempotency_key, expected_import_id = sys.argv[1:3]
    with get_db_connection() as conn:
        roots = conn.execute(
            "SELECT id, requester_id, request_hash, status FROM upload_imports "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchall()
        if len(roots) != 1:
            raise AssertionError(f"expected exactly one accepted root, got {len(roots)}")
        root = dict(roots[0])
        if root["id"] != expected_import_id:
            raise AssertionError("database root differs from the browser accepted response")
        if not root["request_hash"] or len(root["request_hash"]) != 64:
            raise AssertionError("accepted root is missing its canonical request hash")

        attempts = conn.execute(
            "SELECT attempt_no, status FROM upload_attempts WHERE import_id = ? ORDER BY attempt_no",
            (root["id"],),
        ).fetchall()
        if len(attempts) != 1:
            raise AssertionError(f"expected one accepted attempt, got {len(attempts)}")
        jobs = conn.execute(
            "SELECT id, job_type, status FROM jobs WHERE root_import_id = ? ORDER BY id",
            (root["id"],),
        ).fetchall()
        if not jobs:
            raise AssertionError("accepted root has no durable outbox job")

        print(json.dumps({
            "idempotency_key": idempotency_key,
            "root": root,
            "attempts": [dict(row) for row in attempts],
            "jobs": [dict(row) for row in jobs],
            "root_count_for_rejected_and_corrected_key": len(roots),
            "attempt_count": len(attempts),
        }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

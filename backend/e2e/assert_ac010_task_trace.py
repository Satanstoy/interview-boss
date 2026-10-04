"""Assert AC-010's browser trace matches disposable SQLite ownership/state."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: assert_ac010_task_trace.py USER1_IMPORT_ID USER2_IMPORT_ID "
            "USER2_RECOVERABLE_IMPORT_ID"
        )
    import_ids = sys.argv[1:]
    expected_state = {
        import_ids[0]: ("running", 7),
        import_ids[1]: ("running", 8),
        import_ids[2]: ("partial_failed", 4),
    }
    rows = []
    with get_db_connection() as conn:
        for import_id in import_ids:
            root = conn.execute(
                "SELECT id, requester_id, status, revision, current_attempt_no "
                "FROM upload_imports WHERE id = ?",
                (import_id,),
            ).fetchone()
            if root is None:
                raise AssertionError(f"AC-010 root missing from disposable DB: {import_id}")
            expected_status, expected_revision = expected_state[import_id]
            if root["status"] != expected_status or int(root["revision"]) != expected_revision:
                raise AssertionError(f"unexpected final root state: {dict(root)}")
            attempts = int(
                conn.execute(
                    "SELECT COUNT(*) FROM upload_attempts WHERE import_id = ?", (import_id,)
                ).fetchone()[0]
            )
            jobs = int(
                conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE root_import_id = ?", (import_id,)
                ).fetchone()[0]
            )
            if attempts != 1 or jobs != 1:
                raise AssertionError(
                    f"account switch/recovery created extra work for {import_id}: "
                    f"attempts={attempts}, jobs={jobs}"
                )
            rows.append(
                {
                    **dict(root),
                    "attempt_count": attempts,
                    "job_count": jobs,
                    "progress_checkpoint_count": int(
                        conn.execute(
                            "SELECT COUNT(*) FROM upload_stage_results "
                            "WHERE import_id = ? AND stage = 'extract' AND status = 'succeeded'",
                            (import_id,),
                        ).fetchone()[0]
                    ),
                }
            )
    if rows[0]["requester_id"] == rows[1]["requester_id"]:
        raise AssertionError("AC-010 U1 and U2 tasks unexpectedly share one owner")
    if rows[1]["requester_id"] != rows[2]["requester_id"]:
        raise AssertionError("the recoverable failure is not owned by U2")
    print(json.dumps({"roots": rows, "attempt_and_job_counts_unchanged": True}, sort_keys=True))


if __name__ == "__main__":
    main()

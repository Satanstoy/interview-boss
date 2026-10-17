"""Hold accepted roots in a deterministic running state for real-stack AC-010."""

from __future__ import annotations

import hashlib
import json
import sys

from app.db.connection import get_db_connection


def _progress_checkpoint(import_id: str, pipeline_version: str) -> tuple[str, str]:
    payload = {
        "提取计数": {
            "extracted": 1,
            "retained": 1,
            "excluded": 0,
            "needs_review": 0,
        },
        "具体题目清单": [f"{import_id} AC-010 held question"],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: prepare_ac010_tasks.py IMPORT_ID [IMPORT_ID ...]")
    import_ids = sys.argv[1:]
    results = []
    with get_db_connection() as conn:
        for import_id in import_ids:
            root = conn.execute(
                "SELECT id, requester_id, pipeline_version, current_attempt_no "
                "FROM upload_imports WHERE id = ?",
                (import_id,),
            ).fetchone()
            if root is None:
                raise AssertionError(f"accepted upload root not found: {import_id}")
            job = conn.execute(
                "SELECT id, upload_attempt_id FROM jobs WHERE root_import_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (import_id,),
            ).fetchone()
            if job is None:
                raise AssertionError(f"accepted root has no real job: {import_id}")

            attempt_no = max(1, int(root["current_attempt_no"] or 0))
            conn.execute(
                "UPDATE upload_imports SET status = 'running', current_attempt_no = ?, "
                "revision = 8, error_code = NULL, error_message = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (attempt_no, import_id),
            )
            conn.execute(
                "UPDATE jobs SET status = 'running', progress_phase = 'answer', "
                "progress_total = 1, progress_current = 0 WHERE id = ?",
                (int(job["id"]),),
            )
            if job["upload_attempt_id"] is not None:
                conn.execute(
                    "UPDATE upload_attempts SET status = 'active' WHERE id = ?",
                    (int(job["upload_attempt_id"]),),
                )
            checkpoint, output_hash = _progress_checkpoint(
                import_id, str(root["pipeline_version"])
            )
            conn.execute(
                "INSERT OR IGNORE INTO upload_stage_results "
                "(import_id, stage, unit_key, input_version, pipeline_version, status, "
                "result_json, output_hash, retryable, job_id) "
                "VALUES (?, 'extract', 'document', 1, ?, 'succeeded', ?, ?, 0, ?)",
                (
                    import_id,
                    str(root["pipeline_version"]),
                    checkpoint,
                    output_hash,
                    int(job["id"]),
                ),
            )
            results.append(
                {
                    "import_id": import_id,
                    "owner_id": int(root["requester_id"]),
                    "job_id": int(job["id"]),
                    "attempt_no": attempt_no,
                    "status": "running",
                    "revision": 8,
                    "progress": {"completed": 0, "total": 1},
                }
            )
        conn.commit()
    print(json.dumps({"roots": results}, ensure_ascii=False, sort_keys=True))


def set_revision(import_id: str, revision: int) -> dict:
    with get_db_connection() as conn:
        cursor = conn.execute(
            "UPDATE upload_imports SET revision = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'running'",
            (revision, import_id),
        )
        if cursor.rowcount != 1:
            raise AssertionError(f"could not set running root {import_id} to revision {revision}")
        conn.commit()
        row = conn.execute(
            "SELECT id, requester_id, status, revision FROM upload_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        return dict(row)


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--revision":
    print(json.dumps(set_revision(sys.argv[2], int(sys.argv[3])), ensure_ascii=False, sort_keys=True))
elif __name__ == "__main__":
    main()

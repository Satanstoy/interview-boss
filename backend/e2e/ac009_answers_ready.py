"""Return success only after both isolated answer jobs have durable results."""

from __future__ import annotations

import sys

from app.db.connection import get_db_connection


def main() -> None:
    import_ids = sys.argv[1:]
    if len(import_ids) != 2:
        raise SystemExit("expected two upload import IDs")
    with get_db_connection() as conn:
        for import_id in import_ids:
            rows = conn.execute(
                "SELECT j.status, q.ai_answer FROM jobs j "
                "JOIN question_bank q ON j.work_key = 'answer:' || q.id || ':v1' "
                "WHERE j.root_import_id = ? AND j.job_type = 'generate_answer'",
                (import_id,),
            ).fetchall()
            if len(rows) != 1 or rows[0]["status"] != "completed" or not rows[0]["ai_answer"]:
                raise SystemExit(1)


if __name__ == "__main__":
    main()

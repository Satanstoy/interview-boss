"""Capture durable counts immediately before AC-024 legacy list refreshes."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


TABLES = (
    "upload_imports",
    "upload_attempts",
    "public_contribution_requests",
    "jd",
    "interview",
    "question_bank",
    "questions_detail",
    "question_resolutions",
    "analysis_queue",
)


def main() -> None:
    with get_db_connection() as conn:
        counts = {
            "submit_import_jobs": int(
                conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'submit_import'").fetchone()[0]
            ),
            "generate_answer_jobs": int(
                conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'generate_answer'").fetchone()[0]
            ),
        }
        counts.update(
            {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in TABLES
            }
        )
    with open(sys.argv[1], "w", encoding="utf-8") as stream:
        json.dump(counts, stream, ensure_ascii=False, indent=2)
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

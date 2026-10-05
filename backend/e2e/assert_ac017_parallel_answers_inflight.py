"""Assert AC-017 retry requests overlap with two claimed answer jobs."""

from __future__ import annotations

import json
import time
import urllib.request

from app.db.connection import get_db_connection
from e2e.seed_ac017_retry_chain import IMPORT_ID


def main() -> None:
    deadline = time.monotonic() + 15
    access = {}
    jobs = []
    while time.monotonic() < deadline:
        with urllib.request.urlopen("http://llm-stub:8080/__e2e/access", timeout=5) as response:
            access = json.loads(response.read().decode("utf-8"))
        with get_db_connection() as conn:
            root = conn.execute(
                "SELECT current_attempt_no, status FROM upload_imports WHERE id = ?", (IMPORT_ID,)
            ).fetchone()
            attempt = conn.execute(
                "SELECT id, status FROM upload_attempts WHERE import_id = ? AND attempt_no = 3",
                (IMPORT_ID,),
            ).fetchone()
            jobs = conn.execute(
                "SELECT id, job_type, status, root_import_id, upload_attempt_id, work_key "
                "FROM jobs WHERE root_import_id = ? AND job_type = 'generate_answer' "
                "ORDER BY work_key",
                (IMPORT_ID,),
            ).fetchall()
        parallel = access.get("parallel_answers", {})
        if (
            root is not None
            and int(root["current_attempt_no"]) == 3
            and attempt is not None
            and attempt["status"] == "active"
            and len(jobs) == 2
            and all(job["status"] == "running" for job in jobs)
            and int(parallel.get("active", 0)) == 2
        ):
            break
        time.sleep(0.05)
    else:
        raise AssertionError(
            f"expected two running answer jobs in the provider during same-root retries: "
            f"jobs={[dict(row) for row in jobs]} provider={access.get('parallel_answers')}"
        )

    work_keys = {row["work_key"] for row in jobs}
    markers = access["parallel_answers"].get("markers", {})
    if work_keys != {"answer:1:v1", "answer:2:v1"}:
        raise AssertionError(f"unexpected in-flight work keys: {sorted(work_keys)}")
    if any(markers.get(marker) != 1 for marker in ("AC017_PARALLEL_ANSWER_A", "AC017_PARALLEL_ANSWER_B")):
        raise AssertionError(f"each answer marker must be in flight once: {markers}")

    print(
        json.dumps(
            {
                "root_import_id": IMPORT_ID,
                "current_attempt_no": 3,
                "attempt_c": dict(attempt),
                "running_answer_jobs": [dict(row) for row in jobs],
                "provider_parallel_answers": access["parallel_answers"],
                "browser_retries_overlap": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

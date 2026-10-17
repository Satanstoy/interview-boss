"""Seed the A/B/C retry history used by the AC-017 real-stack scenario."""

from __future__ import annotations

import hashlib
import json

from app.core.auth import hash_password
from app.db.connection import get_db_connection
from app.services.upload_repository import UPLOAD_PIPELINE_VERSION_DEFAULT


OWNER = "ac017_owner"
PASSWORD = "Ac017-cross-generation-retry-real-stack-123!"
IMPORT_ID = "imp-ac017-cross-generation-retry"
QUESTION_A = "AC017_PARALLEL_ANSWER_A: explain optimistic locking."
QUESTION_B = "AC017_PARALLEL_ANSWER_B: explain queue idempotency."
ANSWER_A = "AC017_PARALLEL_ANSWER_A_RESULT"
ANSWER_B = "AC017_PARALLEL_ANSWER_B_RESULT"
SUCCESS_CHECKPOINT = {"extracted": "AC017 preserved successful checkpoint"}


def main() -> None:
    with get_db_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (OWNER,)).fetchone():
            raise RuntimeError("AC-017 disposable owner unexpectedly already exists")
        owner_id = int(
            conn.execute(
                "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                "VALUES (?, ?, ?, 0, 'private') RETURNING id",
                (OWNER, hash_password(PASSWORD), f"{OWNER}@example.test"),
            ).fetchone()["id"]
        )
        conn.execute(
            "INSERT INTO user_llm_config (user_id, api_key, base_url, model, timeout) "
            "VALUES (?, ?, ?, ?, '10')",
            (owner_id, "real-stack-e2e-provider-key", "http://llm-stub:8080/v1", "real-stack-stub"),
        )

        payload = {
            "raw_text": "AC017 stable retry lineage and parallel answer source",
            "image_data": [],
            "url": "https://ac017.example/retry-lineage",
            "content_type_hint": "interview",
            "target": "personal",
            "target_intent": "private",
            "user_id": owner_id,
            "is_admin": False,
            "entry": "api",
        }
        policy = {
            "credential_scope": "user",
            "write_scope": "personal",
            "target_intent": "private",
            "source_type": "interview",
        }
        conn.execute(
            "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
            "target_intent, source_type, resolved_type, pipeline_version, policy_json, "
            "payload_json, status, current_attempt_no, revision, error_code, error_message) "
            "VALUES (?, ?, 'ac017-retry-key', ?, 'private', 'interview', 'interview', ?, ?, ?, "
            "'partial_failed', 3, 9, 'UPSTREAM_TIMEOUT', 'AC017 retry fixture')",
            (
                IMPORT_ID,
                owner_id,
                hashlib.sha256(IMPORT_ID.encode()).hexdigest(),
                UPLOAD_PIPELINE_VERSION_DEFAULT,
                json.dumps(policy, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
            ),
        )

        attempts = {}
        for attempt_no, status in ((1, "failed"), (2, "failed"), (3, "active")):
            attempts[attempt_no] = int(
                conn.execute(
                    "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
                    "VALUES (?, ?, ?, ?) RETURNING id",
                    (IMPORT_ID, attempt_no, status, owner_id),
                ).fetchone()["id"]
            )

        job_a = int(
            conn.execute(
                "INSERT INTO jobs (job_type, status, progress_total, created_by, root_import_id, "
                "upload_attempt_id, work_key, idempotency_key, last_error, completed_at) "
                "VALUES ('submit_import', 'failed', 6, ?, ?, ?, 'extract:document:v1', "
                "'ac017:attempt-a', 'AC017 attempt A failed', CURRENT_TIMESTAMP) RETURNING id",
                (owner_id, IMPORT_ID, attempts[1]),
            ).fetchone()["id"]
        )
        job_b = int(
            conn.execute(
                "INSERT INTO jobs (job_type, status, progress_total, created_by, parent_job_id, "
                "root_import_id, upload_attempt_id, work_key, idempotency_key, last_error, "
                "completed_at) VALUES ('submit_import', 'failed', 6, ?, ?, ?, ?, "
                "'classify:question-batch', 'ac017:attempt-b', 'AC017 attempt B failed', "
                "CURRENT_TIMESTAMP) RETURNING id",
                (owner_id, job_a, IMPORT_ID, attempts[2]),
            ).fetchone()["id"]
        )
        job_c = int(
            conn.execute(
                "INSERT INTO jobs (job_type, status, progress_total, created_by, parent_job_id, "
                "root_import_id, upload_attempt_id, work_key, idempotency_key) "
                "VALUES ('submit_import', 'queued', 6, ?, ?, ?, ?, 'extract:document:v1', "
                "'ac017:attempt-c') RETURNING id",
                (owner_id, job_b, IMPORT_ID, attempts[3]),
            ).fetchone()["id"]
        )

        checkpoint_json = json.dumps(SUCCESS_CHECKPOINT, ensure_ascii=False, sort_keys=True)
        checkpoint_hash = hashlib.sha256(checkpoint_json.encode()).hexdigest()
        conn.execute(
            "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
            "pipeline_version, status, result_json, output_hash, retryable, job_id) "
            "VALUES (?, 'extract', 'document', 1, ?, 'succeeded', ?, ?, 0, ?)",
            (IMPORT_ID, UPLOAD_PIPELINE_VERSION_DEFAULT, checkpoint_json, checkpoint_hash, job_a),
        )
        conn.execute(
            "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
            "pipeline_version, status, error_code, retryable, job_id) "
            "VALUES (?, 'classify', 'question-batch', 1, ?, 'failed', 'UPSTREAM_TIMEOUT', 1, ?)",
            (IMPORT_ID, UPLOAD_PIPELINE_VERSION_DEFAULT, job_b),
        )

        question_ids = []
        for question in (QUESTION_A, QUESTION_B):
            question_ids.append(
                int(
                    conn.execute(
                        "INSERT INTO question_bank (question, cat1, cat2, frequency, sources, "
                        "owner_id, submitted_by, status, job_position) "
                        "VALUES (?, '后端', '系统设计', 1, '[]', ?, ?, 'approved', '') "
                        "RETURNING id",
                        (question, owner_id, owner_id),
                    ).fetchone()["id"]
                )
            )
        conn.commit()

    print(
        json.dumps(
            {
                "import_id": IMPORT_ID,
                "owner_id": owner_id,
                "owner_username": OWNER,
                "attempt_ids": attempts,
                "job_ids": {"A": job_a, "B": job_b, "C": job_c},
                "question_ids": question_ids,
                "questions": [QUESTION_A, QUESTION_B],
                "expected_answers": [ANSWER_A, ANSWER_B],
                "success_checkpoint_hash": checkpoint_hash,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

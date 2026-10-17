"""Seed running and recoverable tasks for the real API/SSE AC-010 test."""

from __future__ import annotations

import hashlib
import json

from app.core.auth import hash_password
from app.db.connection import get_db_connection
from app.services.upload_repository import UPLOAD_PIPELINE_VERSION_DEFAULT


PASSWORD = "Ac010-real-stack-account-switch-123!"
USERS = ("ac010_u1", "ac010_u2")


def main() -> None:
    roots = []
    with get_db_connection() as conn:
        for ordinal, username in enumerate(USERS, start=1):
            email = f"{username}@example.test"
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                "VALUES (?, ?, ?, 0, 'private')",
                (username, hash_password(PASSWORD), email),
            )
            user_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO user_llm_config (user_id, api_key, base_url, model, timeout) "
                "VALUES (?, 'real-stack-e2e-provider-key', 'http://llm-stub:8080/v1', "
                "'real-stack-stub', '10')",
                (user_id,),
            )

            import_id = f"imp-ac010-real-stack-u{ordinal}"
            idempotency_key = f"ac010-real-stack-u{ordinal}-key"
            payload = {
                "raw_text": f"AC010_PRIVATE_USER_{ordinal}_SOURCE",
                "image_data": [],
                "url": f"https://ac010.example/u{ordinal}",
                "season": "2027届暑期实习",
                "content_type_hint": "interview",
                "target": "personal",
                "target_intent": "private",
                "user_id": user_id,
                "is_admin": False,
                "job_position": "后端开发工程师",
                "entry": "api",
            }
            policy = {
                "credential_scope": "user",
                "write_scope": "personal",
                "target_intent": "private",
                "source_type": "interview",
            }
            request_hash = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            conn.execute(
                "INSERT INTO upload_imports "
                "(id, requester_id, idempotency_key, request_hash, target_intent, source_type, "
                "resolved_type, position_name, pipeline_version, policy_json, payload_json, status, "
                "current_attempt_no, revision, error_code, error_message) "
                "VALUES (?, ?, ?, ?, 'private', 'interview', 'interview', ?, ?, ?, ?, "
                "'running', 1, 8, NULL, NULL)",
                (
                    import_id,
                    user_id,
                    idempotency_key,
                    request_hash,
                    "后端开发工程师",
                    UPLOAD_PIPELINE_VERSION_DEFAULT,
                    json.dumps(policy, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            attempt_id = int(
                conn.execute(
                    "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
                    "VALUES (?, 1, 'active', ?) RETURNING id",
                    (import_id, user_id),
                ).fetchone()["id"]
            )
            job_id = int(
                conn.execute(
                    "INSERT INTO jobs (job_type, status, progress_total, progress_current, "
                    "progress_phase, created_by, root_import_id, upload_attempt_id, work_key) "
                    "VALUES ('submit_import', 'running', 1, 0, 'answer', ?, ?, ?, ?) "
                    "RETURNING id",
                    (user_id, import_id, attempt_id, f"ac010:answer:{ordinal}"),
                ).fetchone()["id"]
            )
            checkpoint = {
                "提取计数": {
                    "extracted": 1,
                    "retained": 1,
                    "excluded": 0,
                    "needs_review": 0,
                },
                "具体题目清单": [f"AC010 user {ordinal} private question"],
            }
            result_json = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True)
            output_hash = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO upload_stage_results "
                "(import_id, stage, unit_key, input_version, pipeline_version, status, "
                "result_json, output_hash, retryable, job_id) "
                "VALUES (?, 'extract', 'document', 1, ?, 'succeeded', ?, ?, 0, ?)",
                (
                    import_id,
                    UPLOAD_PIPELINE_VERSION_DEFAULT,
                    result_json,
                    output_hash,
                    job_id,
                ),
            )
            roots.append(
                {
                    "username": username,
                    "user_id": user_id,
                    "import_id": import_id,
                    "job_id": job_id,
                    "attempt_id": attempt_id,
                    "status": "running",
                    "revision": 8,
                }
            )

        user2_id = roots[1]["user_id"]
        failed_import_id = "imp-ac010-real-stack-u2-recoverable"
        failed_payload = {
            "raw_text": "AC010_PRIVATE_USER_2_RECOVERABLE_SOURCE",
            "image_data": [],
            "url": "https://ac010.example/u2-recoverable",
            "season": "2027届暑期实习",
            "content_type_hint": "interview",
            "target": "personal",
            "target_intent": "private",
            "user_id": user2_id,
            "is_admin": False,
            "job_position": "后端开发工程师",
            "entry": "api",
        }
        failed_policy = {
            "credential_scope": "user",
            "write_scope": "personal",
            "target_intent": "private",
            "source_type": "interview",
        }
        request_hash = hashlib.sha256(
            json.dumps(failed_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        conn.execute(
            "INSERT INTO upload_imports "
            "(id, requester_id, idempotency_key, request_hash, target_intent, source_type, "
            "resolved_type, position_name, pipeline_version, policy_json, payload_json, status, "
            "current_attempt_no, revision, error_code, error_message) "
            "VALUES (?, ?, 'ac010-u2-recoverable-key', ?, 'private', 'interview', 'interview', "
            "'后端开发工程师', ?, ?, ?, 'partial_failed', 1, 4, 'UPSTREAM_TIMEOUT', "
            "'AC010 retryable fixture failure')",
            (
                failed_import_id,
                user2_id,
                request_hash,
                UPLOAD_PIPELINE_VERSION_DEFAULT,
                json.dumps(failed_policy, ensure_ascii=False),
                json.dumps(failed_payload, ensure_ascii=False),
            ),
        )
        failed_attempt_id = int(
            conn.execute(
                "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
                "VALUES (?, 1, 'failed', ?) RETURNING id",
                (failed_import_id, user2_id),
            ).fetchone()["id"]
        )
        failed_job_id = int(
            conn.execute(
                "INSERT INTO jobs (job_type, status, progress_total, progress_current, "
                "progress_phase, created_by, root_import_id, upload_attempt_id, work_key, "
                "last_error, completed_at) "
                "VALUES ('submit_import', 'failed', 1, 1, 'answer', ?, ?, ?, ?, ?, "
                "CURRENT_TIMESTAMP) RETURNING id",
                (
                    user2_id,
                    failed_import_id,
                    failed_attempt_id,
                    "ac010:u2:retryable-answer",
                    "AC010 retryable fixture failure",
                ),
            ).fetchone()["id"]
        )
        failed_extract = {
            "提取计数": {"extracted": 1, "retained": 1, "excluded": 0, "needs_review": 0},
            "具体题目清单": ["AC010 user 2 recoverable question"],
        }
        failed_extract_json = json.dumps(failed_extract, ensure_ascii=False, sort_keys=True)
        failed_extract_hash = hashlib.sha256(failed_extract_json.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO upload_stage_results "
            "(import_id, stage, unit_key, input_version, pipeline_version, status, "
            "result_json, output_hash, retryable, job_id) "
            "VALUES (?, 'extract', 'document', 1, ?, 'succeeded', ?, ?, 0, ?)",
            (
                failed_import_id,
                UPLOAD_PIPELINE_VERSION_DEFAULT,
                failed_extract_json,
                failed_extract_hash,
                failed_job_id,
            ),
        )
        conn.execute(
            "INSERT INTO upload_stage_results "
            "(import_id, stage, unit_key, input_version, pipeline_version, status, "
            "error_code, retryable, job_id) "
            "VALUES (?, 'answer', 'answer:ac010-q1', 1, ?, 'failed', 'UPSTREAM_TIMEOUT', 1, ?)",
            (failed_import_id, UPLOAD_PIPELINE_VERSION_DEFAULT, failed_job_id),
        )
        roots.append(
            {
                "username": roots[1]["username"],
                "user_id": user2_id,
                "import_id": failed_import_id,
                "job_id": failed_job_id,
                "attempt_id": failed_attempt_id,
                "status": "partial_failed",
                "revision": 4,
            }
        )
        conn.commit()
    print(json.dumps({"password": PASSWORD, "roots": roots}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

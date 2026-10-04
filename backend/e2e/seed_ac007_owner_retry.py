"""Seed a recoverable failed private upload for real-stack AC-007."""

from __future__ import annotations

import hashlib
import json
import os

from app.core.auth import hash_password
from app.db.connection import get_db_connection
from app.services.upload_repository import UPLOAD_PIPELINE_VERSION_DEFAULT


OWNER = "ac007_owner"
OTHER = "ac007_other"
PASSWORD = "Ac007-owner-retry-real-stack-123!"
IMPORT_ID = "imp-ac007-owner-retry-real-stack"
POSITION = "agent开发/大模型应用开发/大模型开发"
CHECKPOINT_QUESTION = "AC007 checkpoint question: explain database transaction isolation."


def main() -> None:
    with get_db_connection() as conn:
        user_ids = {}
        for username in (OWNER, OTHER):
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                    "VALUES (?, ?, ?, 0, 'private')",
                    (username, hash_password(PASSWORD), f"{username}@example.test"),
                )
                user_id = int(cursor.lastrowid)
            else:
                user_id = int(row["id"])
            user_ids[username] = user_id

        conn.execute(
            "INSERT OR REPLACE INTO user_llm_config "
            "(user_id, api_key, base_url, model, timeout) "
            "VALUES (?, ?, ?, ?, '10')",
            (
                user_ids[OWNER],
                "real-stack-e2e-provider-key",
                "http://llm-stub:8080/v1",
                "real-stack-stub",
            ),
        )

        payload = {
            "raw_text": "AC007_OWNER_RETRY_REAL_STACK source text",
            "image_data": [],
            "url": "https://ac007.example/recoverable-source",
            "season": "2027届暑期实习",
            "content_type_hint": "interview",
            "target": "personal",
            "target_intent": "private",
            "user_id": user_ids[OWNER],
            "is_admin": False,
            "job_position": POSITION,
            "entry": "api",
        }
        policy = {
            "credential_scope": "user",
            "write_scope": "personal",
            "target_intent": "private",
            "source_type": "interview",
        }
        conn.execute(
            "INSERT INTO upload_imports "
            "(id, requester_id, idempotency_key, request_hash, target_intent, source_type, "
            "resolved_type, position_name, pipeline_version, policy_json, payload_json, status, "
            "current_attempt_no, revision, error_code, error_message) "
            "VALUES (?, ?, 'ac007-owner-retry-key', ?, 'private', 'interview', 'interview', ?, "
            "?, ?, ?, 'partial_failed', 1, 7, 'UPSTREAM_TIMEOUT', 'AC007 recoverable fixture')",
            (
                IMPORT_ID,
                user_ids[OWNER],
                hashlib.sha256(IMPORT_ID.encode()).hexdigest(),
                POSITION,
                UPLOAD_PIPELINE_VERSION_DEFAULT,
                json.dumps(policy, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        attempt_id = int(
            conn.execute(
                "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
                "VALUES (?, 1, 'failed', ?) RETURNING id",
                (IMPORT_ID, user_ids[OWNER]),
            ).fetchone()["id"]
        )
        job_id = int(
            conn.execute(
                "INSERT INTO jobs (job_type, status, progress_total, created_by, root_import_id, "
                "upload_attempt_id, work_key, last_error, completed_at) "
                "VALUES ('submit_import', 'failed', 6, ?, ?, ?, 'extract:document:v1', "
                "'AC007 recoverable failure', CURRENT_TIMESTAMP) RETURNING id",
                (user_ids[OWNER], IMPORT_ID, attempt_id),
            ).fetchone()["id"]
        )
        checkpoint = {
            "doc_type": "interview",
            "data": {
                "公司": "AC007_OWNER_RETRY_REAL_STACK 公司",
                "面试轮次": "一面",
                "考察重点": "数据库事务",
                "难易程度": "中等",
                "具体题目清单": [CHECKPOINT_QUESTION],
                "题目 ordinal": [1],
                "题目标记": {},
                "提取计数": {"extracted": 1, "retained": 1, "excluded": 0, "needs_review": 0},
            },
            "url": payload["url"],
        }
        checkpoint_json = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True)
        checkpoint_hash = hashlib.sha256(checkpoint_json.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO upload_stage_results "
            "(import_id, stage, unit_key, input_version, pipeline_version, status, "
            "result_json, output_hash, retryable, job_id) "
            "VALUES (?, 'extract', 'document', 1, ?, 'succeeded', ?, ?, 0, ?)",
            (
                IMPORT_ID,
                UPLOAD_PIPELINE_VERSION_DEFAULT,
                checkpoint_json,
                checkpoint_hash,
                job_id,
            ),
        )
        conn.execute(
            "INSERT INTO upload_stage_results "
            "(import_id, stage, unit_key, input_version, pipeline_version, status, "
            "error_code, retryable, job_id) "
            "VALUES (?, 'classify', 'question-batch', 1, ?, 'failed', 'UPSTREAM_TIMEOUT', 1, ?)",
            (IMPORT_ID, UPLOAD_PIPELINE_VERSION_DEFAULT, job_id),
        )
        conn.commit()

        admin_username = os.environ.get("ADMIN_USERNAME", "real_stack_admin")
        admin = conn.execute(
            "SELECT id, email FROM users WHERE username = ? AND is_admin = 1", (admin_username,)
        ).fetchone()
        if admin is None:
            raise RuntimeError("AC-007 disposable administrator is missing")
        if not admin["email"]:
            conn.execute(
                "UPDATE users SET email = ? WHERE id = ?",
                ("ac007-admin@example.test", int(admin["id"])),
            )
            conn.commit()
        print(json.dumps({
            "import_id": IMPORT_ID,
            "owner_username": OWNER,
            "owner_id": user_ids[OWNER],
            "other_username": OTHER,
            "other_id": user_ids[OTHER],
            "password": PASSWORD,
            "admin_username": admin_username,
            "admin_id": int(admin["id"]),
            "job_id": job_id,
            "attempt_id": attempt_id,
            "checkpoint_hash": checkpoint_hash,
            "checkpoint_question": CHECKPOINT_QUESTION,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()

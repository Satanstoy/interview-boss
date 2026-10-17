"""Seed AC-011's stable interview/questions and real answer-worker work items."""

from __future__ import annotations

import hashlib
import json

from app.core.auth import hash_password
from app.core.prompts import DEFAULT_TAXONOMY
from app.db.connection import get_db_connection
from app.services.job_lifecycle import create_answer_generation_jobs
from app.services.upload_repository import UPLOAD_PIPELINE_VERSION_DEFAULT
from app.services.question_resolution import record_resolution


USERNAME = "ac011_partial_answers"
TEST_PASSWORD = "Ac011-partial-answer-real-stack-123!"
IMPORT_ID = "imp-ac011-partial-answer-real-stack"
COMPANY = "AC011 部分答案恢复演练"
SOURCE_URL = "https://ac011.example/partial-answer"
MARKER = "AC011_ANSWER_PARTIAL_REAL_STACK"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    with get_db_connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ?", (USERNAME,)).fetchone()
        if user is None:
            user_id = int(
                conn.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                    "VALUES (?, ?, ?, 0, 'private') RETURNING id",
                    (USERNAME, hash_password(TEST_PASSWORD), f"{USERNAME}@example.test"),
                ).fetchone()["id"]
            )
        else:
            user_id = int(user["id"])

        conn.execute(
            "INSERT OR REPLACE INTO user_llm_config "
            "(user_id, api_key, base_url, model, timeout) "
            "VALUES (?, 'real-stack-e2e-provider-key', 'http://llm-stub:8080/v1', "
            "'real-stack-stub', '10')",
            (user_id,),
        )

        position_name = DEFAULT_TAXONOMY["job_position"]
        position = conn.execute(
            "SELECT id FROM job_positions WHERE name = ? AND (is_deleted = 0 OR is_deleted IS NULL) "
            "ORDER BY id LIMIT 1",
            (position_name,),
        ).fetchone()
        if position is None:
            position_id = int(
                conn.execute(
                    "INSERT INTO job_positions (name, description) VALUES (?, 'AC-011 fixture') "
                    "RETURNING id",
                    (position_name,),
                ).fetchone()["id"]
            )
        else:
            position_id = int(position["id"])
        conn.execute("UPDATE users SET current_position_id = ? WHERE id = ?", (position_id, user_id))

        interview_id = int(
            conn.execute(
                "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, "
                "season, owner_id, status, job_position) VALUES (?, ?, '一面', ?, ?, '中等', "
                "'2026秋招', ?, 'approved', ?) RETURNING id",
                (
                    SOURCE_URL,
                    COMPANY,
                    "仅恢复失败答案",
                    "\n".join(f"{i}. AC011_QUESTION_{i:02d} 题目 {i}" for i in range(1, 11)),
                    user_id,
                    position_name,
                ),
            ).fetchone()["id"]
        )

        payload = {
            "raw_text": f"{MARKER}\n" + "\n".join(f"{i}. 题目 {i}" for i in range(1, 11)),
            "image_data": [],
            "url": SOURCE_URL,
            "season": "2026秋招",
            "content_type_hint": "interview",
            "target": "personal",
            "target_intent": "private",
            "user_id": user_id,
            "is_admin": False,
            "job_position": position_name,
            "entry": "api",
        }
        policy = {
            "policy_version": 1,
            "pipeline_version": UPLOAD_PIPELINE_VERSION_DEFAULT,
            "requester_id": user_id,
            "target_intent": "private",
            "write_scope": "private",
            "owner_id": user_id,
            "credential_scope": "user",
            "payer": {"type": "user", "user_id": user_id},
            "request_public_review": False,
            "public_review_required": False,
            "source_type": "interview",
            "position_id": position_id,
            "position_name": position_name,
        }
        conn.execute(
            "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
            "target_intent, source_type, resolved_type, position_id, position_name, pipeline_version, "
            "policy_json, payload_json, status, current_attempt_no, interview_id, revision) "
            "VALUES (?, ?, 'ac011-partial-answer-key', ?, 'private', 'interview', 'interview', ?, ?, ?, ?, ?, "
            "'queued', 1, ?, 1)",
            (
                IMPORT_ID,
                user_id,
                _hash(MARKER),
                position_id,
                position_name,
                UPLOAD_PIPELINE_VERSION_DEFAULT,
                json.dumps(policy, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
                interview_id,
            ),
        )
        attempt_id = int(
            conn.execute(
                "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
                "VALUES (?, 1, 'active', ?) RETURNING id",
                (IMPORT_ID, user_id),
            ).fetchone()["id"]
        )
        submit_job_id = int(
            conn.execute(
                "INSERT INTO jobs (job_type, status, progress_total, progress_current, created_by, "
                "root_import_id, upload_attempt_id, work_key, lease_generation, result, completed_at) "
                "VALUES ('submit_import', 'completed', 6, 6, ?, ?, ?, 'extract:document:v1', 1, ?, "
                "CURRENT_TIMESTAMP) RETURNING id",
                (
                    user_id,
                    IMPORT_ID,
                    attempt_id,
                    json.dumps({"interview_id": interview_id, "question_count": 10}),
                ),
            ).fetchone()["id"]
        )
        conn.execute(
            "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
            (submit_job_id, json.dumps(payload, ensure_ascii=False)),
        )

        extracted = {
            "doc_type": "interview",
            "提取计数": {"extracted": 10, "retained": 10, "excluded": 0, "needs_review": 0},
            "data": {
                "公司": COMPANY,
                "面试轮次": "一面",
                "考察重点": "仅恢复失败答案",
                "难易程度": "中等",
                "具体题目清单": [f"AC011_QUESTION_{i:02d} 题目 {i}" for i in range(1, 11)],
                "题目 ordinal": list(range(1, 11)),
            },
            "url": SOURCE_URL,
        }
        tagged_rows = []
        for index in range(10):
            question = f"AC011_QUESTION_{index + 1:02d} 题目 {index + 1}"
            tagged_rows.append(
                [SOURCE_URL, COMPANY, "一面", question, "C.基础工程能力", "C1.系统设计", "失败恢复", "L2-中等"]
            )
        checkpoints = [
            ("extract", "document", extracted),
            ("classify", "question-batch", {"tagged_rows": tagged_rows}),
            ("persist", "document", {"interview_id": interview_id, "detail_count": 10}),
        ]
        for stage, unit_key, result in checkpoints:
            result_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
            conn.execute(
                "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
                "pipeline_version, status, result_json, output_hash, retryable, job_id) "
                "VALUES (?, ?, ?, 1, ?, 'succeeded', ?, ?, 0, ?)",
                (IMPORT_ID, stage, unit_key, UPLOAD_PIPELINE_VERSION_DEFAULT, result_json, _hash(result_json), submit_job_id),
            )

        answer_tasks = []
        detail_ids = []
        for index in range(10):
            ordinal = index + 1
            question = f"AC011_QUESTION_{ordinal:02d} 题目 {ordinal}"
            answer = f"AC011_QUESTION_{ordinal:02d}_ANSWER：已完成的稳定答案。" if ordinal <= 8 else ""
            question_id = int(
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, "
                    "ai_answer, owner_id, submitted_by, status, job_position) "
                    "VALUES (?, 'C.基础工程能力', 'C1.系统设计', '失败恢复', 'L2-中等', 1, ?, ?, ?, "
                    "'approved', ?) RETURNING id",
                    (question, answer, user_id, user_id, position_name),
                ).fetchone()["id"]
            )
            conn.execute("UPDATE question_bank SET cluster_id = ? WHERE id = ?", (question_id, question_id))
            detail_id = int(
                conn.execute(
                    "INSERT INTO questions_detail (interview_id, question, cat1, cat2, tags, difficulty, "
                    "url, company, round, owner_id, status, job_position, import_id, source_ordinal) "
                    "VALUES (?, ?, 'C.基础工程能力', 'C1.系统设计', '失败恢复', 'L2-中等', ?, ?, '一面', ?, "
                    "'approved', ?, ?, ?) RETURNING id",
                    (interview_id, question, SOURCE_URL, COMPANY, user_id, position_name, IMPORT_ID, ordinal),
                ).fetchone()["id"]
            )
            detail_ids.append(detail_id)
            conn.execute(
                "INSERT INTO analysis_queue (interview_id, question_detail_id, owner_id, status, "
                "root_import_id, pipeline_version) VALUES (?, ?, ?, 'done', ?, ?)",
                (interview_id, detail_id, user_id, IMPORT_ID, UPLOAD_PIPELINE_VERSION_DEFAULT),
            )
            record_resolution(
                conn,
                detail_id=detail_id,
                occurrence_scope="private",
                occurrence_owner_id=user_id,
                canonical_id=question_id,
                canonical_scope="private",
                status="created",
                pipeline_version=UPLOAD_PIPELINE_VERSION_DEFAULT,
                input_version=1,
            )
            answer_tasks.append((question_id, question))

        answer_job_ids = create_answer_generation_jobs(
            conn,
            submit_job_id,
            answer_tasks,
            user_id,
            skip_search=True,
            llm_scope="user",
            search_scope="user",
        )
        persist_checkpoint_json = json.dumps(
            {"interview_id": interview_id, "detail_ids": detail_ids}, ensure_ascii=False, sort_keys=True
        )
        conn.execute(
            "UPDATE upload_stage_results SET result_json = ?, output_hash = ? "
            "WHERE import_id = ? AND stage = 'persist' AND unit_key = 'document'",
            (persist_checkpoint_json, _hash(persist_checkpoint_json), IMPORT_ID),
        )

        conn.commit()
        print(
            json.dumps(
                {
                    "import_id": IMPORT_ID,
                    "user_id": user_id,
                    "username": USERNAME,
                    "password": TEST_PASSWORD,
                    "interview_id": interview_id,
                    "position_id": position_id,
                    "submit_job_id": submit_job_id,
                    "attempt_id": attempt_id,
                    "question_ids": [task[0] for task in answer_tasks],
                    "detail_ids": detail_ids,
                    "answer_job_ids": answer_job_ids,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()

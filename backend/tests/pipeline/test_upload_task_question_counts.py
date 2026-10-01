"""AC-011: root snapshots count question outcomes, never checkpoint rows."""

from __future__ import annotations

import json


def test_snapshot_progress_uses_extracted_question_and_answer_outcomes(test_db):
    from app.routers.upload_imports import _snapshot, _stage_counts

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101, 'progress-user', 'x')"
    )
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, status, current_attempt_no) "
        "VALUES ('progress-root', 101, 'progress-key', 'progress-hash', 'private', "
        "'interview', 'upload-pipeline-v1', 'partial_failed', 1)"
    )
    test_db.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES ('progress-root', 1, 'failed', 101)"
    )
    test_db.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, pipeline_version, "
        "status, result_json) VALUES ('progress-root', 'extract', 'document', "
        "'upload-pipeline-v1', 'succeeded', ?) ",
        (json.dumps({"提取计数": {"extracted": 10, "retained": 10, "excluded": 0}}),),
    )
    # Additional stage checkpoints are not additional questions.
    for stage in ("classify", "resolve", "persist"):
        test_db.execute(
            "INSERT INTO upload_stage_results (import_id, stage, unit_key, pipeline_version, status) "
            "VALUES ('progress-root', ?, 'document', 'upload-pipeline-v1', 'succeeded')",
            (stage,),
        )
    for ordinal in range(10):
        test_db.execute(
            "INSERT INTO upload_stage_results (import_id, stage, unit_key, pipeline_version, "
            "status, job_id, error_code) VALUES ('progress-root', 'answer', ?, "
            "'upload-pipeline-v1', ?, NULL, ?)",
            (
                f"answer:{ordinal + 1}",
                "succeeded" if ordinal < 8 else "failed",
                None if ordinal < 8 else "UPSTREAM_TIMEOUT",
            ),
        )
    test_db.commit()

    root = test_db.execute(
        "SELECT * FROM upload_imports WHERE id = 'progress-root'"
    ).fetchone()
    counts = _stage_counts(test_db, "progress-root")
    snapshot = _snapshot(root, counts=counts, conn=test_db)

    assert counts["total"] == 10
    assert counts["answered"] == 8
    assert counts["failed"] == 2
    assert snapshot["progress"] == {"unit": "questions", "completed": 10, "total": 10}


def test_answer_jobs_are_bound_to_upload_root_and_keep_attempt_open(test_db):
    from app.services.job_lifecycle import create_answer_generation_jobs
    from app.services.upload_lifecycle import finalize_attempt_and_aggregate_root

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101, 'answer-user', 'x')"
    )
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, status, current_attempt_no) "
        "VALUES ('answer-root', 101, 'answer-key', 'answer-hash', 'private', "
        "'interview', 'upload-pipeline-v1', 'running', 1)"
    )
    test_db.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES ('answer-root', 1, 'active', 101)"
    )
    attempt_id = test_db.execute(
        "SELECT id FROM upload_attempts WHERE import_id = 'answer-root'"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id, "
        "work_key, lease_generation) VALUES ('submit_import', 'completed', 101, "
        "'answer-root', ?, 'extract:document:v1', 1)",
        (attempt_id,),
    )
    parent_job_id = test_db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    test_db.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, pipeline_version, status) "
        "VALUES ('answer-root', 'extract', 'document', 'upload-pipeline-v1', 'succeeded')"
    )

    answer_ids = create_answer_generation_jobs(
        test_db,
        parent_job_id,
        [(901, "解释幂等性")],
        user_id=101,
        llm_scope="user",
    )
    assert len(answer_ids) == 1
    child = test_db.execute(
        "SELECT root_import_id, upload_attempt_id, parent_job_id FROM jobs WHERE id = ?",
        (answer_ids[0],),
    ).fetchone()
    assert child["root_import_id"] == "answer-root"
    assert child["upload_attempt_id"] == attempt_id
    assert child["parent_job_id"] == parent_job_id
    stage = test_db.execute(
        "SELECT status, job_id FROM upload_stage_results WHERE import_id = 'answer-root' "
        "AND stage = 'answer' AND unit_key = 'answer:901'"
    ).fetchone()
    assert stage["status"] == "pending"
    assert stage["job_id"] == answer_ids[0]

    aggregate = finalize_attempt_and_aggregate_root(
        test_db,
        import_id="answer-root",
        actor_id=101,
        lease_generation=1,
    )
    assert aggregate["status"] == "queued"
    assert test_db.execute(
        "SELECT status FROM upload_attempts WHERE id = ?", (attempt_id,)
    ).fetchone()[0] == "active"

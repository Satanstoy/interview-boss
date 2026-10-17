"""Regression coverage for retrying a failed upload classification checkpoint."""

from __future__ import annotations

import asyncio
import json

from app.agents.submit.classify import classify_node
from app.services.upload_repository import get_stage_result, save_stage_result


def test_successful_classification_retry_replaces_failed_checkpoint(
    app_db_isolation, monkeypatch
):
    conn = app_db_isolation
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-classify-retry', 101, 'key', 'hash', 'private', 'interview', 'v1')"
    )
    conn.execute(
        "INSERT INTO jobs (job_type, status, root_import_id, lease_generation) "
        "VALUES ('submit_import', 'running', 'imp-classify-retry', 7)"
    )
    job_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    save_stage_result(
        conn,
        import_id="imp-classify-retry",
        stage="extract",
        unit_key="document",
        input_version=1,
        pipeline_version="v1",
        status="succeeded",
        result_json='{"data":{"具体题目清单":["数据库事务"]}}',
        output_hash="extract-checkpoint-hash",
        job_id=job_id,
    )
    save_stage_result(
        conn,
        import_id="imp-classify-retry",
        stage="classify",
        unit_key="question-batch",
        input_version=1,
        pipeline_version="v1",
        status="failed",
        error_code="UPSTREAM_TIMEOUT",
        retryable=True,
        job_id=job_id,
    )
    conn.commit()

    async def fake_tag_questions_batch(**_kwargs):
        return [
            ["url", "测试公司", "一面", "数据库事务", "后端", "数据库基础", "事务", "L2"]
        ]

    from app.db import connection as db_connection

    # Importing the graph's service module initializes the process LLM client.
    # This regression only exercises checkpoint persistence and never calls a
    # provider, so keep that module initialization offline and deterministic.
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("OPENAI_API_KEY", "checkpoint-test-key")
    from app.services import submit_service

    monkeypatch.setattr(
        db_connection,
        "get_taxonomy_for_position",
        lambda **_kwargs: {"configured": True, "categories": []},
    )
    monkeypatch.setattr(
        submit_service, "tag_questions_batch", fake_tag_questions_batch
    )

    result = asyncio.run(
        classify_node(
            {
                "import_id": "imp-classify-retry",
                "job_id": job_id,
                "_lease_generation": 7,
                "user_id": 101,
                "credential_scope": "user",
                "job_position": "后端",
                "extracted_data": {
                    "公司": "测试公司",
                    "面试轮次": "一面",
                    "具体题目清单": ["数据库事务"],
                },
            }
        )
    )

    checkpoint = get_stage_result(
        conn,
        import_id="imp-classify-retry",
        stage="classify",
        unit_key="question-batch",
        input_version=1,
    )
    assert result["tagged_rows"]
    assert checkpoint["status"] == "succeeded"
    assert checkpoint["error_code"] is None
    assert checkpoint["retryable"] == 0
    assert json.loads(checkpoint["result_json"])["tagged_rows"] == result["tagged_rows"]
    assert get_stage_result(
        conn,
        import_id="imp-classify-retry",
        stage="extract",
        unit_key="document",
        input_version=1,
    )["output_hash"] == "extract-checkpoint-hash"

import asyncio
import json
from app.services.upload_policy import resolve_upload_policy


def test_expired_submit_node_still_writes(app_db_isolation):
    from app.agents.submit.persist_public import persist_public_node
    from app.services.job_lifecycle import assert_job_fence, JobFenceError

    conn = app_db_isolation
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (201, 'audit-admin', 'x', 1)"
    )
    policy = resolve_upload_policy(
        actor_id=201, actor_is_admin=True, target_intent="share", position_name="后端开发"
    ).to_policy_json()
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, target_intent, source_type, pipeline_version, policy_json) VALUES ('audit-root',201,'audit-key','audit-hash','share','interview','upload-pipeline-v1',?)",
        (json.dumps(policy),),
    )
    conn.execute(
        "INSERT INTO jobs (job_type,status,root_import_id,lease_generation,locked_until) VALUES ('submit_import','running','audit-root',2,datetime('now','+120 seconds'))"
    )
    jid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    try:
        assert_job_fence(conn, jid, 1)
        raise AssertionError("stale generation unexpectedly accepted")
    except JobFenceError:
        pass
    result = asyncio.run(
        persist_public_node(
            {
                "import_id": "audit-root",
                "job_id": jid,
                "_lease_generation": 1,
                "user_id": 201,
                "is_admin": True,
                "job_position": "后端开发",
                "saved_url": "https://audit.invalid/post",
                "extracted_data": {"具体题目清单": ["事务隔离级别是什么"], "公司": "x"},
                "tagged_rows": [
                    ["url", "x", "一面", "事务隔离级别是什么", "后端", "数据库基础", "事务", "L2"]
                ],
            }
        )
    )
    assert conn.execute("SELECT count(*) FROM interview").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM questions_detail").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM analysis_queue").fetchone()[0] == 1
    print("STALE_GENERATION_WROTE_INTERVIEW_DETAIL_QUEUE", result["saved_interview_id"])

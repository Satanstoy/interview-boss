"""SQLite fault injection at real private persistence boundaries."""

import json
import sqlite3

import pytest

from app.agents.submit.persist_personal import match_and_persist_personal_node
from app.services.upload_policy import resolve_upload_policy


@pytest.mark.parametrize("fault", ["queue", "resolution", "contribution", "root_bind", "valid", "stale"])
async def test_private_persistence_transaction(app_db_isolation, fault):
    conn = app_db_isolation
    conn.execute(
        "INSERT INTO users(id,username,password_hash) VALUES(202,'atomic-user','TEST_HASH')"
    )
    policy = resolve_upload_policy(
        actor_id=202, actor_is_admin=False, target_intent="private", position_name="后端开发"
    ).to_policy_json()
    conn.execute(
        "INSERT INTO upload_imports(id,requester_id,idempotency_key,request_hash,target_intent,source_type,pipeline_version,policy_json) VALUES('atomic-root',202,'atomic-key','atomic-hash','private','interview','upload-pipeline-v1',?)",
        (json.dumps(policy),),
    )
    job_id = conn.execute(
        "INSERT INTO jobs(job_type,status,root_import_id,lease_generation,locked_until) VALUES('submit_import','running','atomic-root',1,datetime('now','+120 seconds'))"
    ).lastrowid
    if fault in ("queue", "resolution"):
        table = "analysis_queue" if fault == "queue" else "question_resolutions"
        conn.execute(
            f"CREATE TRIGGER fail_atomic_write BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'atomic write failure'); END"
        )
    if fault == "contribution":
        conn.execute("CREATE TRIGGER fail_contribution BEFORE INSERT ON public_contribution_requests BEGIN SELECT RAISE(ABORT,'atomic write failure'); END")
    if fault == "root_bind":
        conn.execute("CREATE TRIGGER fail_root_bind BEFORE UPDATE OF contribution_request_id ON upload_imports WHEN NEW.contribution_request_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'atomic write failure'); END")
    conn.commit()
    state = {
        "import_id": "atomic-root",
        "job_id": job_id,
        "_lease_generation": 1,
        "_input_version": 1,
        "user_id": 202,
        "is_admin": False,
        "request_public_review": fault in ("contribution", "root_bind"),
        "job_position": "后端开发",
        "saved_url": "https://test.invalid/atomic",
        "extracted_data": {"具体题目清单": ["ATOMIC_QUESTION"]},
        "tagged_rows": [["url", "", "", "ATOMIC_QUESTION", "后端", "数据库基础", "事务", "L2"]],
    }
    if fault == "valid":
        result = await match_and_persist_personal_node(state)
        assert result["saved_interview_id"] is not None
        detail = conn.execute("SELECT import_id,source_ordinal FROM questions_detail").fetchone()
        assert tuple(detail) == ("atomic-root", 1)
        assert conn.execute("SELECT COUNT(*) FROM analysis_queue").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_resolutions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0] == 0
        return
    if fault == "stale":
        from app.services.job_lifecycle import JobFenceError

        state["_lease_generation"] = 0
        with pytest.raises(JobFenceError):
            await match_and_persist_personal_node(state)
    else:
        with pytest.raises(sqlite3.IntegrityError, match="atomic write failure"):
            await match_and_persist_personal_node(state)
    for table in ["interview", "questions_detail", "analysis_queue", "question_resolutions", "public_contribution_requests"]:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

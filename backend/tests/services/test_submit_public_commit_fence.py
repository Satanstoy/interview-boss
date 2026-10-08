"""Actual public persistence must fence its business transaction."""

import json

import pytest

from app.agents.submit.persist_public import persist_public_node
from app.services.job_lifecycle import JobFenceError
from app.services.upload_policy import resolve_upload_policy


@pytest.mark.parametrize(
    "invalid",
    [
        "valid",
        "generation",
        "expired",
        "completed",
        "missing_identity",
        "wrong_root",
        "input_version",
        "cancelled",
    ],
)
async def test_public_persistence_rejects_invalid_execution_without_results(
    app_db_isolation, invalid
):
    conn = app_db_isolation
    conn.execute(
        "INSERT INTO users(id,username,password_hash,is_admin) VALUES(201,'fence-admin','TEST_HASH',1)"
    )
    policy = resolve_upload_policy(
        actor_id=201, actor_is_admin=True, target_intent="share", position_name="后端开发"
    ).to_policy_json()
    conn.execute(
        "INSERT INTO upload_imports(id,requester_id,idempotency_key,request_hash,target_intent,source_type,pipeline_version,policy_json) VALUES('fence-root',201,'fence-key','fence-hash','share','interview','upload-pipeline-v1',?)",
        (json.dumps(policy),),
    )
    jid = conn.execute(
        "INSERT INTO jobs(job_type,status,root_import_id,lease_generation,locked_until) VALUES('submit_import','running','fence-root',2,datetime('now','+120 seconds'))"
    ).lastrowid
    state = {
        "import_id": "fence-root",
        "job_id": jid,
        "_lease_generation": 2,
        "_input_version": 1,
        "user_id": 201,
        "is_admin": True,
        "job_position": "后端开发",
        "saved_url": "https://test.invalid/fence",
        "extracted_data": {"具体题目清单": ["FENCE_QUESTION"]},
        "tagged_rows": [["url", "", "", "FENCE_QUESTION", "后端", "数据库基础", "事务", "L2"]],
    }
    if invalid == "generation":
        state["_lease_generation"] = 1
    elif invalid == "expired":
        conn.execute("UPDATE jobs SET locked_until=datetime('now','-1 second') WHERE id=?", (jid,))
    elif invalid == "completed":
        conn.execute("UPDATE jobs SET status='completed' WHERE id=?", (jid,))
    elif invalid == "missing_identity":
        state.pop("job_id")
    elif invalid == "wrong_root":
        conn.execute("UPDATE jobs SET root_import_id=NULL WHERE id=?", (jid,))
    elif invalid == "input_version":
        conn.execute("UPDATE upload_imports SET input_version=2 WHERE id='fence-root'")
    elif invalid == "cancelled":
        conn.execute(
            "UPDATE upload_imports SET status='failed',error_code='SOURCE_DELETED' WHERE id='fence-root'"
        )
    conn.commit()
    if invalid == "valid":
        result = await persist_public_node(state)
        assert result["saved_interview_id"] is not None
        for table in [
            "interview",
            "questions_detail",
            "analysis_queue",
            "public_contribution_requests",
        ]:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1, table
        assert (
            conn.execute(
                "SELECT reviewed_by,projection_hash FROM public_contribution_requests"
            ).fetchone()["reviewed_by"]
            == 201
        )
        return
    with pytest.raises((JobFenceError, ValueError, PermissionError)):
        await persist_public_node(state)
    for table in [
        "interview",
        "questions_detail",
        "analysis_queue",
        "public_contribution_requests",
        "admin_audit_log",
    ]:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


async def test_stale_jd_persistence_leaves_no_business_row(app_db_isolation):
    from app.agents.submit.persist_personal import jd_persist_node
    conn = app_db_isolation
    conn.execute("INSERT INTO users(id,username,password_hash) VALUES(202,'jd-fence-user','TEST_HASH')")
    conn.execute("INSERT INTO upload_imports(id,requester_id,idempotency_key,request_hash,target_intent,source_type,pipeline_version) VALUES('jd-fence-root',202,'jd-fence-key','hash','private','jd','upload-pipeline-v1')")
    job = conn.execute("INSERT INTO jobs(job_type,status,root_import_id,lease_generation,locked_until) VALUES('submit_import','running','jd-fence-root',2,datetime('now','+120 seconds'))").lastrowid
    conn.commit()
    with pytest.raises(JobFenceError):
        await jd_persist_node({'user_id':202,'target':'personal','import_id':'jd-fence-root','job_id':job,'_lease_generation':1,'_input_version':1,'extracted_data':{'岗位名称':'FENCE_JD'},'saved_url':'https://test.invalid/jd-fence'})
    assert conn.execute('SELECT COUNT(*) FROM jd').fetchone()[0] == 0

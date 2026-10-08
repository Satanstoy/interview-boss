"""A worker may finalize only its accepted version and its own checkpoints."""

import json

import pytest

from app.services.upload_credentials import resolve_upload_credentials


@pytest.mark.parametrize("change", ["generation", "input", "progress_input", "valid"])
async def test_submit_finalization_preserves_foreign_or_stale_checkpoints(
    app_db_isolation, monkeypatch, change
):
    from app import worker

    conn = app_db_isolation
    conn.execute(
        "INSERT INTO users(id,username,password_hash) VALUES(9401,'finalize-owner','TEST_HASH')"
    )
    conn.execute(
        "INSERT INTO user_llm_config(user_id,api_key,base_url,model) VALUES(9401,'TEST_KEY_PLACEHOLDER','https://test.invalid/v1','test-model')"
    )
    conn.execute(
        "INSERT INTO upload_imports(id,requester_id,idempotency_key,request_hash,target_intent,source_type,pipeline_version,input_version,policy_json) VALUES('finalize-root',9401,'finalize-key','hash','private','jd','upload-pipeline-v1',2,'{\"credential_scope\":\"user\"}')"
    )
    preflight = conn.execute(
        "INSERT INTO jobs(job_type,status,root_import_id) VALUES('credential_preflight','completed','finalize-root')"
    ).lastrowid
    conn.execute(
        "INSERT INTO job_payloads(job_id,payload) VALUES(?,?)",
        (preflight, json.dumps({"credential_scope": "user"})),
    )
    fingerprint = resolve_upload_credentials(
        credential_scope="user", user_id=9401, stage="extract"
    ).config_fingerprint
    conn.execute(
        "INSERT INTO upload_stage_results(import_id,stage,unit_key,input_version,pipeline_version,status,job_id,result_json) VALUES('finalize-root','credential_preflight','user',2,'upload-pipeline-v1','succeeded',?,?)",
        (preflight, json.dumps({"config_fingerprint": fingerprint, "model": "test-model"})),
    )
    job = conn.execute(
        "INSERT INTO jobs(job_type,status,root_import_id) VALUES('submit_import','pending','finalize-root')"
    ).lastrowid
    conn.execute(
        "INSERT INTO job_payloads(job_id,payload) VALUES(?,?)",
        (job, json.dumps({"user_id": 9401, "target": "personal"})),
    )
    child = conn.execute(
        "INSERT INTO jobs(job_type,status,root_import_id) VALUES('cluster_batch','running','finalize-root')"
    ).lastrowid
    conn.execute(
        "INSERT INTO upload_stage_results(import_id,stage,unit_key,input_version,pipeline_version,status,job_id) VALUES('finalize-root','classify','old-version',1,'upload-pipeline-v1','running',?)",
        (job,),
    )
    conn.execute(
        "INSERT INTO upload_stage_results(import_id,stage,unit_key,input_version,pipeline_version,status,job_id) VALUES('finalize-root','cluster','child',2,'upload-pipeline-v1','running',?)",
        (child,),
    )
    conn.commit()
    before = []
    root_before = {}

    async def completed_graph(state, result_collector):
        result_collector["final_state"] = {
            "doc_type": "JD",
            "target": "personal",
            "extracted_data": {},
        }
        if change == "generation":
            conn.execute("UPDATE jobs SET lease_generation=lease_generation+1 WHERE id=?", (job,))
        if change in ("input", "progress_input"):
            conn.execute("UPDATE upload_imports SET input_version=3 WHERE id='finalize-root'")
        conn.commit()
        before.extend(
            tuple(row) for row in conn.execute("SELECT * FROM upload_stage_results ORDER BY id")
        )
        root_before.update(
            dict(
                conn.execute(
                    "SELECT status,revision,error_code,error_message FROM upload_imports WHERE id='finalize-root'"
                ).fetchone()
            )
        )
        if change == "progress_input":
            yield 'data: {"type":"progress","step":"tag","message":"tagging"}\n\n'
        yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr("app.agents.submit.graph.stream_submit_graph", completed_graph)
    await worker.submit_import_task({}, job)
    if change != "valid":
        assert [
            tuple(row) for row in conn.execute("SELECT * FROM upload_stage_results ORDER BY id")
        ] == before
        assert (
            dict(
                conn.execute(
                    "SELECT status,revision,error_code,error_message FROM upload_imports WHERE id='finalize-root'"
                ).fetchone()
            )
            == root_before
        )
    else:
        assert (
            conn.execute(
                "SELECT status FROM upload_stage_results WHERE unit_key='old-version'"
            ).fetchone()[0]
            == "running"
        )
        assert (
            conn.execute(
                "SELECT status FROM upload_stage_results WHERE unit_key='child'"
            ).fetchone()[0]
            == "running"
        )
        assert (
            conn.execute(
                "SELECT status FROM upload_stage_results WHERE stage='extract' AND job_id=? AND input_version=2",
                (job,),
            ).fetchone()[0]
            == "succeeded"
        )

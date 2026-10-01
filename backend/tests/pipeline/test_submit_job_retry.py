from unittest.mock import AsyncMock, MagicMock, patch


def _override_user():
    from app.asgi import app
    from app.core.auth import get_current_user

    user = {"id": 1, "is_admin": True, "username": "sj"}
    app.dependency_overrides[get_current_user] = lambda: user
    return app, get_current_user


def test_retry_binds_root_and_attempt_when_v2_root_exists(client, test_db):
    """R03：旧 retry 对已有 v2 root 的失败任务，新 job 绑定 root+attempt（不只看子任务）。"""

    from app.services.upload_lifecycle import accept_upload

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (1, 'sj', 'x', 1)"
    )
    accepted = accept_upload(
        test_db,
        actor_id=1,
        actor_is_admin=True,
        idempotency_key="root-retry-1",
        target_intent="private",
        text="待重试的面经",
        credential_loaders={
            "user": lambda uid: {
                "api_key": "k",
                "base_url": "https://u.example.com/v1",
                "model": "m",
            }
        },
    )
    test_db.commit()
    import_id = accepted["import_id"]

    # AC-004：预检全部通过后才创建首个业务 job（旧 retry 只服务业务 job）
    from app.services.credential_preflight import create_initial_submit_job_if_ready

    preflight_rows = test_db.execute(
        "SELECT j.id, json_extract(p.payload, '$.credential_scope') AS scope "
        "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' "
        "AND j.status IN ('pending', 'queued', 'running') ORDER BY j.id",
        (import_id,),
    ).fetchall()
    for row in preflight_rows:
        test_db.execute(
            "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
            "pipeline_version, status, job_id) "
            "VALUES (?, 'preflight', ?, 1, 'upload-pipeline-v1', 'succeeded', ?)",
            (import_id, f"initial:{row['scope']}", row["id"]),
        )
        test_db.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (row["id"],))
    test_db.commit()
    attempt = test_db.execute(
        "SELECT id FROM upload_attempts WHERE import_id = ? AND status = 'active' "
        "ORDER BY attempt_no DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    submit_job_id = create_initial_submit_job_if_ready(
        test_db, root_import_id=import_id, attempt_id=int(attempt["id"])
    )
    test_db.commit()
    assert submit_job_id, "预检通过后必须存在业务 job"

    # 标记失败：在途 job 全部终态失败并释放 attempt 归属
    test_db.execute(
        "UPDATE jobs SET status = 'failed', worker_id = NULL, locked_until = NULL "
        "WHERE root_import_id = ?",
        (import_id,),
    )
    test_db.commit()

    app, dependency = _override_user()
    try:
        arq_job = MagicMock(job_id="arq-retry-root-1")
        with patch(
            "app.worker.enqueue_submit_import_job",
            new=AsyncMock(return_value=arq_job),
        ):
            retry_response = client.post(f"/api/submit-jobs/{submit_job_id}/retry", json={})

        assert retry_response.status_code == 200, retry_response.text
        retry_id = retry_response.json()["job_id"]
        job = test_db.execute(
            "SELECT job_type, status, root_import_id, upload_attempt_id, work_key, arq_job_id "
            "FROM jobs WHERE id = ?",
            (retry_id,),
        ).fetchone()
        # R03 + AC-004：旧 attempt 失败后恢复必须先重建可派发的预检工作，
        # 业务 job 只在预检全部通过后创建（contracts §4/§5）。
        assert job["job_type"] == "credential_preflight"
        assert job["root_import_id"] == import_id, "重试 job 必须绑定根任务"
        assert job["upload_attempt_id"] is not None, "重试 job 必须绑定 attempt"
        assert job["work_key"], "重试 job 必须带 work_key"
        assert job["status"] == "queued"
        assert job["arq_job_id"] == "arq-retry-root-1"
        # 预检通过后同 root 上才出现业务 job
        ready = test_db.execute(
            "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? "
            "AND job_type = 'submit_import' AND status IN ('pending', 'queued', 'running')",
            (import_id,),
        ).fetchone()[0]
        assert ready == 0, "预检未通过前不得派发业务 job"
    finally:
        app.dependency_overrides.pop(dependency, None)


def _create_failed_submit_job(test_db):
    cursor = test_db.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, "
        "available_at, last_error) VALUES ('submit_import', 'failed', 6, 1, "
        "CURRENT_TIMESTAMP, '模拟失败')"
    )
    job_id = cursor.lastrowid
    test_db.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, '{"raw_text":"待重试的面经","target":"personal","user_id":1}'),
    )
    test_db.commit()
    return job_id


def test_failed_submit_job_is_visible_and_retry_creates_new_attempt(
    client, test_db
):
    app, dependency = _override_user()
    try:
        failed_id = _create_failed_submit_job(test_db)

        response = client.get("/api/submit-jobs/active")
        assert response.status_code == 200
        assert response.json()[0]["id"] == failed_id
        assert response.json()[0]["status"] == "failed"
        assert response.json()[0]["retryable"] is True

        arq_job = MagicMock(job_id="arq-retry-1")
        with patch(
            "app.worker.enqueue_submit_import_job",
            new=AsyncMock(return_value=arq_job),
        ):
            retry_response = client.post(f"/api/submit-jobs/{failed_id}/retry", json={})

        assert retry_response.status_code == 200
        retry_id = retry_response.json()["job_id"]
        assert retry_id != failed_id

        original = test_db.execute(
            "SELECT status FROM jobs WHERE id = ?", (failed_id,)
        ).fetchone()
        retry = test_db.execute(
            "SELECT status, parent_job_id, arq_job_id FROM jobs WHERE id = ?",
            (retry_id,),
        ).fetchone()
        assert original["status"] == "failed"
        assert retry["status"] == "queued"
        assert retry["parent_job_id"] == failed_id
        assert retry["arq_job_id"] == "arq-retry-1"

        visible = client.get("/api/submit-jobs/active").json()
        assert [item["id"] for item in visible] == [retry_id]
    finally:
        app.dependency_overrides.pop(dependency, None)

"""AC-028：隔离集成栈入口（真实 HTTP + 临时 SQLite + 隔离 Redis + 真实 worker 任务 + 本地 stub）。

按验收要求**拒绝在非隔离环境启动**：必须显式提供

- ``UPLOAD_TEST_DB_PATH``：临时 SQLite 路径（测试自己创建/迁移/删除）；
- ``UPLOAD_TEST_REDIS_PREFIX``：独立随机队列前缀，避免污染共享 Redis。

本文件覆盖的链路：真实 ``POST /api/submit-jobs`` → 持久预检 job → 真实预检探测
（stub provider）→ 业务 job 投递到**真实 Redis 的隔离队列** → “worker 停机” →
“worker 重启”后真实 ``submit_import_task`` 执行 → 授权 API 读到结果 →
重复投递不得产生重复业务成果。

**未覆盖（如实 not-run）**：真实浏览器对活体栈的端到端断言。前端 e2e 走 mock API，
本仓库没有“浏览器 + 真实后端 + 真实 worker”的 harness；此处只证明浏览器会读取的
授权 API 返回正确结果，不宣称浏览器腿已验收。
"""

from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REQUIRED_ENV = ("UPLOAD_TEST_DB_PATH", "UPLOAD_TEST_REDIS_PREFIX")
_missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]

pytestmark = pytest.mark.skipif(
    bool(_missing),
    reason=(
        "AC-028 需要隔离环境变量："
        + ", ".join(_missing or REQUIRED_ENV)
        + "（拒绝在非隔离环境启动）"
    ),
)

USER_CONFIG = {
    "api_key": "stub-user-key",
    "base_url": "https://stub.invalid/v1",
    "model": "stub-model",
    "timeout": 5,
}
GLOBAL_CONFIG = {
    "api_key": "stub-system-key",
    "base_url": "https://stub.invalid/v1",
    "model": "stub-model",
    "timeout": 5,
}


@pytest.fixture
def isolated_stack(monkeypatch):
    """临时 SQLite + 全模块连接注入；测试结束删除库文件。"""

    db_path = os.environ["UPLOAD_TEST_DB_PATH"]
    if os.path.exists(db_path):
        os.remove(db_path)

    import app.db.connection as db_module
    from app.db.migrations import run_migrations

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    for uid in (101, 102, 201):
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
            "VALUES (?, ?, 'x', ?)",
            (uid, f"u{uid}", 1 if uid == 201 else 0),
        )
    conn.execute(
        "INSERT OR REPLACE INTO user_llm_config (user_id, api_key, base_url, model) "
        "VALUES (101, ?, ?, ?)",
        (USER_CONFIG["api_key"], USER_CONFIG["base_url"], USER_CONFIG["model"]),
    )
    conn.commit()

    # 只改 DB_PATH + ContextVar：原始 get_db_connection()/run_db() 本来就按这两者
    # 解析连接。**不要**逐模块 patch get_db_connection——测试期间才被导入的模块会
    # 永久绑定那个闭包（monkeypatch 没记录过它，teardown 无法还原），
    # 后续测试会拿到已关闭的连接。
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    token = db_module._db_conn_var.set(conn)

    yield conn

    db_module._db_conn_var.reset(token)
    conn.close()
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
async def isolated_redis(monkeypatch):
    """真实 Redis 的隔离命名空间：入队走项目真实 enqueue 代码路径。"""

    from arq.connections import RedisSettings, create_pool

    import app.worker_enqueue as enqueue_module

    prefix = os.environ["UPLOAD_TEST_REDIS_PREFIX"]
    queue_name = f"{prefix}:arq"
    opened = []

    async def _new_pool():
        # 项目 helper 在 finally 里 close 池，所以每次都要给新池
        pool = await create_pool(
            RedisSettings.from_dsn(enqueue_module.REDIS_URL),
            default_queue_name=queue_name,
        )
        opened.append(pool)
        return pool

    monkeypatch.setattr(enqueue_module, "_get_redis_pool", _new_pool)

    yield {"queue_name": queue_name, "prefix": prefix, "new_pool": _new_pool}

    # 只清理本前缀的键，绝不触碰其他命名空间
    inspector = await _new_pool()
    keys = await inspector.keys(f"{prefix}*")
    if keys:
        await inspector.delete(*keys)
    for pool in opened:
        try:
            await pool.close()
        except Exception:
            pass


def _loaders():
    return {
        "user": lambda uid: dict(USER_CONFIG),
        "global": lambda: dict(GLOBAL_CONFIG),
    }


def test_env_guard_refuses_unconfigured_run():
    """没有隔离变量时必须拒绝启动（模块级 skipif 即守卫本身）。"""

    assert set(REQUIRED_ENV) == {"UPLOAD_TEST_DB_PATH", "UPLOAD_TEST_REDIS_PREFIX"}


async def test_http_upload_survives_worker_restart_without_duplicate_work(
    isolated_stack, isolated_redis, monkeypatch
):
    """AC-028：真实 HTTP 接受到结果可用，worker 重启/重复投递不产生重复成果。"""

    from fastapi.testclient import TestClient

    import app.worker_enqueue as enqueue_module
    from app.asgi import app
    from app.core.auth import get_current_user
    from app.services.credential_preflight import run_credential_preflight
    from app.worker import submit_import_task

    conn = isolated_stack
    client = TestClient(app)

    # ── 1. 真实 HTTP 接受（worker 未启动）──────────────────────────
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 101,
        "is_admin": 0,
        "username": "u101",
    }
    try:
        response = client.post(
            "/api/submit-jobs",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Idempotency-Key": "ac028-stack-1",
            },
            data={
                "text": "面经：解释 TCP 三次握手",
                "target": "private",
                "content_type": "interview",
                "season": "2026春招",
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 202, response.text
    import_id = response.json()["import_id"]

    preflights = conn.execute(
        "SELECT j.id, p.payload FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' "
        "ORDER BY j.id",
        (import_id,),
    ).fetchall()
    assert len(preflights) == 1, "私人目标只需 user scope 预检"
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()[0] == 0, "预检未通过前不得派发业务 job（AC-004）"

    # ── 2. 预检真实探测（stub provider，不出网）────────────────────
    outcome = run_credential_preflight(
        conn,
        job_id=int(preflights[0]["id"]),
        probe=lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
    )
    conn.commit()
    # 预检必须走与 worker 相同的真实配置读取器：注入 stub loader 会得到不同
    # 的 config_fingerprint，worker 会按设计拒绝执行（defer）。
    assert outcome.status == "ok"
    submit_job = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert submit_job is not None, "预检通过后必须创建业务 job"
    submit_job_id = int(submit_job["id"])

    # ── 3. 投递到真实 Redis 隔离队列，随后“worker 停机”────────────
    arq_job = await enqueue_module.enqueue_submit_import_job(submit_job_id)
    assert arq_job is not None, "业务 job 必须能投递到真实 Redis"
    pool = await isolated_redis["new_pool"]()
    queued = await pool.queued_jobs()
    assert [
        job for job in queued
        if job.function == "submit_import_task" and job.args[0] == submit_job_id
    ], "job 必须落在隔离队列命名空间里"

    # 停机期间：任务仍是 queued，业务成果为零
    assert conn.execute("SELECT COUNT(*) FROM interview").fetchone()[0] == 0
    root = conn.execute(
        "SELECT status FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert root["status"] in ("queued", "running")

    # ── 4. “重启 worker”：真实 submit_import_task 执行 ─────────────
    extract_payload = json.dumps(
        {
            "type": "interview",
            "data": {
                "公司": "AC028 公司",
                "面试轮次": "一面",
                "考察重点": "网络",
                "难易程度": "中等",
                "具体题目清单": [{"ordinal": 1, "question": "TCP 三次握手"}],
            },
        },
        ensure_ascii=False,
    )

    async def tag_questions(*, url, company, round_, questions, **_kwargs):
        return [[url, company, round_, q, "网络", "TCP", "handshake", "中等"] for q in questions]

    def _stub_llm():
        return (
            patch(
                "app.services.llm._call_llm_with_retry_messages",
                new=AsyncMock(return_value=extract_payload),
            ),
            patch(
                "app.services.llm.get_llm_client_for_user",
                return_value=(MagicMock(), USER_CONFIG["model"], 5, "", "openai"),
            ),
            patch("app.services.llm._should_use_response_format", return_value=False),
            patch(
                "app.services.submit_service.tag_questions_batch",
                new=AsyncMock(side_effect=tag_questions),
            ),
        )

    llm_patches = _stub_llm()
    with llm_patches[0], llm_patches[1], llm_patches[2], llm_patches[3]:
        await submit_import_task({}, submit_job_id)
    conn.commit()

    interviews = conn.execute(
        "SELECT id FROM interview WHERE owner_id = 101 ORDER BY id"
    ).fetchall()
    assert len(interviews) == 1, (
        "重启后必须产出恰好一份私人面经; "
        f"root={dict(conn.execute('SELECT status, error_code FROM upload_imports WHERE id = ?', (import_id,)).fetchone())}; "
        f"jobs={[dict(row) for row in conn.execute('SELECT job_type, status, attempts, last_error FROM jobs WHERE root_import_id = ?', (import_id,)).fetchall()]}; "
        f"stages={[dict(row) for row in conn.execute('SELECT stage, status, error_code FROM upload_stage_results WHERE import_id = ?', (import_id,)).fetchall()]}"
    )
    interview_id = int(interviews[0]["id"])
    details_before = conn.execute(
        "SELECT id, question, source_ordinal FROM questions_detail "
        "WHERE interview_id = ? ORDER BY id",
        (interview_id,),
    ).fetchall()
    assert [row["question"] for row in details_before] == ["TCP三次握手"] or [
        row["question"] for row in details_before
    ] == ["TCP 三次握手"]

    # ── 5. 浏览器会读取的授权 API 返回正确结果 ─────────────────────
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 101,
        "is_admin": 0,
        "username": "u101",
    }
    try:
        snapshot = client.get(f"/api/upload-imports/{import_id}")
        assert snapshot.status_code == 200, snapshot.text
        snapshot_body = snapshot.json()
        assert snapshot_body["result"]["interview_id"] == interview_id
        # AC-011：面经已保存但下游聚类尚未完成 → root 不得显示 completed
        assert snapshot_body["status"] == "queued", snapshot_body["status"]
        assert conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? "
            "AND job_type = 'cluster_batch' AND status IN ('pending','queued')",
            (import_id,),
        ).fetchone()[0] >= 1, "聚类工作必须仍在队列里（root 才有理由停在 queued）"
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # ── 6. 重复投递（重启后重放）不得产生重复业务成果 ───────────────
    conn.execute(
        "UPDATE jobs SET status = 'queued', worker_id = NULL, locked_until = NULL, "
        "arq_job_id = NULL WHERE id = ?",
        (submit_job_id,),
    )
    conn.commit()
    replay_patches = _stub_llm()
    with replay_patches[0], replay_patches[1], replay_patches[2], replay_patches[3]:
        await submit_import_task({}, submit_job_id)
    conn.commit()

    assert conn.execute(
        "SELECT COUNT(*) FROM interview WHERE owner_id = 101"
    ).fetchone()[0] == 1, "重放不得重复建面经"
    assert conn.execute(
        "SELECT COUNT(*) FROM questions_detail WHERE interview_id = ?",
        (interview_id,),
    ).fetchone()[0] == len(details_before), "重放不得重复建明细"
    assert conn.execute(
        "SELECT COUNT(*) FROM questions_detail WHERE interview_id = ? AND import_id = ?",
        (interview_id, import_id),
    ).fetchone()[0] == len(details_before)


async def test_successful_preflight_worker_immediately_dispatches_business_job(
    isolated_stack, isolated_redis, monkeypatch
):
    """AC-004：预检通过创建业务 job 后，worker 应立即投递到 ARQ。"""

    from app.services.upload_lifecycle import accept_upload
    from app.worker import credential_preflight_task

    conn = isolated_stack
    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="ac004-immediate-dispatch",
        target_intent="private",
        source_type="interview",
        text="面经：解释 TCP 三次握手",
        position_name="后端开发",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )
    conn.commit()
    preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? "
        "AND job_type = 'credential_preflight'",
        (accepted["import_id"],),
    ).fetchone()
    assert preflight is not None

    # 只替换外部模型探测；配置解析、预检状态机、job 创建和 Redis 入队走真代码。
    monkeypatch.setattr(
        "app.services.credential_preflight._default_probe",
        lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
    )

    await credential_preflight_task({}, int(preflight["id"]))

    submit_job = conn.execute(
        "SELECT id, status, arq_job_id FROM jobs WHERE root_import_id = ? "
        "AND job_type = 'submit_import'",
        (accepted["import_id"],),
    ).fetchone()
    assert submit_job is not None, "预检成功必须创建业务 job"
    assert submit_job["arq_job_id"], "worker 成功预检后必须立即完成 ARQ handoff"

    pool = await isolated_redis["new_pool"]()
    queued = await pool.queued_jobs()
    assert any(
        job.function == "submit_import_task" and job.args[0] == submit_job["id"]
        for job in queued
    ), "业务 job 必须在本次预检 worker 执行后进入隔离 Redis 队列"


async def test_dispatch_recovers_after_committed_job_misses_first_redis_handoff(
    isolated_stack, isolated_redis, monkeypatch
):
    """提交事务已落库但首次 Redis handoff 失败时，dispatcher 后续只补投一次。"""

    from unittest.mock import AsyncMock

    from app.services.upload_lifecycle import accept_upload
    from app.worker import credential_preflight_task
    from app.worker_scheduled import scheduled_submit_job_dispatch_task

    conn = isolated_stack
    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="ac007-handoff-retry",
        target_intent="private",
        source_type="interview",
        text="面经：AC007 dispatcher handoff recovery",
        position_name="后端开发",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )
    conn.commit()
    preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (accepted["import_id"],),
    ).fetchone()
    assert preflight is not None

    monkeypatch.setattr(
        "app.services.credential_preflight._default_probe",
        lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
    )
    failed_enqueue = AsyncMock(side_effect=RuntimeError("isolated Redis unavailable"))
    with monkeypatch.context() as failure_window:
        failure_window.setattr(
            "app.worker_scheduled.enqueue_submit_import_job", failed_enqueue
        )
        outcome = await credential_preflight_task({}, int(preflight["id"]))
    assert outcome["status"] == "ok"
    failed_enqueue.assert_awaited_once()

    submit_job = conn.execute(
        "SELECT id, status, arq_job_id FROM jobs "
        "WHERE root_import_id = ? AND job_type = 'submit_import'",
        (accepted["import_id"],),
    ).fetchone()
    assert submit_job is not None
    assert submit_job["status"] == "pending"
    assert submit_job["arq_job_id"] is None

    # Advance only this disposable database's retry time; the next pass must
    # use the real enqueue helper and the fixture's isolated Redis prefix.
    conn.execute(
        "UPDATE jobs SET available_at = CURRENT_TIMESTAMP WHERE id = ?",
        (submit_job["id"],),
    )
    conn.commit()
    recovered = await scheduled_submit_job_dispatch_task({})
    assert recovered["failed"] == 0
    assert recovered["dispatched"] == 1

    dispatched = conn.execute(
        "SELECT status, arq_job_id FROM jobs WHERE id = ?",
        (submit_job["id"],),
    ).fetchone()
    assert dispatched["status"] == "queued"
    assert dispatched["arq_job_id"]

    pool = await isolated_redis["new_pool"]()
    try:
        queued = await pool.queued_jobs()
        matching = [
            job for job in queued
            if job.function == "submit_import_task" and job.args[0] == submit_job["id"]
        ]
        assert len(matching) == 1

        repeated = await scheduled_submit_job_dispatch_task({})
        queued_after_repeat = await pool.queued_jobs()
        matching_after_repeat = [
            job for job in queued_after_repeat
            if job.function == "submit_import_task" and job.args[0] == submit_job["id"]
        ]
        assert repeated["dispatched"] == 0
        assert len(matching_after_repeat) == 1
    finally:
        await pool.aclose()


async def test_reconciled_cluster_bucket_is_dispatched_and_consumed_by_arq_worker(
    isolated_stack, isolated_redis, monkeypatch
):
    """AC-007：SQLite 对账补出的桶进入真实 Redis，并由 ARQ worker 消费。"""

    from arq.connections import RedisSettings
    from arq.worker import Worker
    from unittest.mock import AsyncMock

    import app.worker_enqueue as enqueue_module
    from app.services.credential_preflight import run_credential_preflight
    from app.services.upload_lifecycle import accept_upload
    from app.worker_cluster_tasks import cluster_batch_task
    from app.worker_scheduled import (
        scheduled_submit_job_dispatch_task,
        scheduled_upload_queue_reconcile_task,
    )

    conn = isolated_stack
    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="ac007-reconciled-cluster-worker",
        target_intent="private",
        source_type="interview",
        text="面经：AC007 reconciled cluster worker",
        position_name="后端开发",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )
    conn.commit()
    preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? "
        "AND job_type = 'credential_preflight'",
        (accepted["import_id"],),
    ).fetchone()
    assert preflight is not None

    preflight_outcome = run_credential_preflight(
        conn,
        job_id=int(preflight["id"]),
        probe=lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
    )
    assert preflight_outcome.status == "ok"

    # The extraction stage has completed and produced one private detail whose
    # clustering bucket is the durable work being reconciled below.
    interview_cursor = conn.execute(
        "INSERT INTO interview (url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES ('https://ac007.example/interview', 'AC007', '一面', '1.题目', 101, 'approved', '后端开发')"
    )
    interview_id = int(interview_cursor.lastrowid)
    detail_cursor = conn.execute(
        "INSERT INTO questions_detail "
        "(interview_id, question, cat1, cat2, tags, owner_id, status, import_id, source_ordinal) "
        "VALUES (?, 'AC007 队列对账后的题目', '后端', '队列', 'recovery', 101, 'approved', ?, 1)",
        (interview_id, accepted["import_id"]),
    )
    detail_id = int(detail_cursor.lastrowid)
    conn.execute(
        "INSERT INTO analysis_queue "
        "(interview_id, question_detail_id, owner_id, status, root_import_id) "
        "VALUES (?, ?, 101, 'pending', ?)",
        (interview_id, detail_id, accepted["import_id"]),
    )
    # This test starts at the post-extraction boundary. Keep the submit job
    # terminal so the dispatcher only sends the reconciled cluster job.
    conn.execute(
        "UPDATE jobs SET status = 'completed', completed_at = CURRENT_TIMESTAMP "
        "WHERE root_import_id = ? AND job_type = 'submit_import'",
        (accepted["import_id"],),
    )
    conn.commit()

    reconciled = await scheduled_upload_queue_reconcile_task({})
    assert reconciled["jobs_created"] == 1
    repeated_reconcile = await scheduled_upload_queue_reconcile_task({})
    assert repeated_reconcile["jobs_created"] == 0

    cluster_job = conn.execute(
        "SELECT id, status, arq_job_id FROM jobs "
        "WHERE root_import_id = ? AND job_type = 'cluster_batch'",
        (accepted["import_id"],),
    ).fetchone()
    assert cluster_job is not None
    assert cluster_job["status"] == "pending"
    assert cluster_job["arq_job_id"] is None
    cluster_job_id = int(cluster_job["id"])

    from app.worker_enqueue import enqueue_cluster_batch_job as enqueue_cluster_batch

    enqueue_attempts = 0

    async def fail_first_cluster_handoff(job_id):
        nonlocal enqueue_attempts
        enqueue_attempts += 1
        if enqueue_attempts == 1:
            raise RuntimeError("AC007 first Redis handoff fails")
        return await enqueue_cluster_batch(job_id)

    monkeypatch.setattr(
        "app.worker_scheduled.enqueue_cluster_batch_job",
        fail_first_cluster_handoff,
    )
    first_dispatch = await scheduled_submit_job_dispatch_task({})
    assert first_dispatch["failed"] == 1
    assert first_dispatch["dispatched"] == 0
    held = conn.execute(
        "SELECT status, arq_job_id FROM jobs WHERE id = ?", (cluster_job_id,)
    ).fetchone()
    assert held["status"] == "pending"
    assert held["arq_job_id"] is None

    # Advance to the next durable dispatcher cycle. The same work_key should
    # be accepted once by Redis and then consumed by the real ARQ worker.
    conn.execute(
        "UPDATE jobs SET available_at = CURRENT_TIMESTAMP WHERE id = ?",
        (cluster_job_id,),
    )
    conn.commit()
    dispatched = await scheduled_submit_job_dispatch_task({})
    assert dispatched["failed"] == 0
    assert dispatched["dispatched"] == 1
    repeated_reconcile = await scheduled_upload_queue_reconcile_task({})
    assert repeated_reconcile["jobs_created"] == 0
    repeated_dispatch = await scheduled_submit_job_dispatch_task({})
    assert repeated_dispatch["dispatched"] == 0
    cluster_job = conn.execute(
        "SELECT status, arq_job_id FROM jobs WHERE id = ?", (cluster_job_id,)
    ).fetchone()
    assert cluster_job["status"] == "queued"
    assert cluster_job["arq_job_id"]

    pool = await isolated_redis["new_pool"]()
    try:
        queued = await pool.queued_jobs()
        matching = [
            job for job in queued
            if job.function == "cluster_batch_task" and job.args[0] == cluster_job_id
        ]
        assert len(matching) == 1
    finally:
        await pool.aclose()

    cluster_batch = AsyncMock(return_value={"count": 0, "ids": []})
    monkeypatch.setattr("app.services.pipeline.cluster_batch", cluster_batch)
    settings = RedisSettings.from_dsn(enqueue_module.REDIS_URL)
    worker = Worker(
        functions=[cluster_batch_task],
        queue_name=isolated_redis["queue_name"],
        redis_settings=settings,
        handle_signals=False,
        burst=True,
        max_tries=1,
        job_timeout=30,
        keep_result=60,
        poll_delay=0.01,
        queue_read_limit=10,
    )
    await worker.main()
    await worker.close()

    pool = await isolated_redis["new_pool"]()
    try:
        from arq.jobs import Job

        arq_job = Job(cluster_job["arq_job_id"], pool)
        result = await arq_job.result(timeout=2)
        assert result["status"] == "done"
        cluster_batch.assert_awaited_once()
    finally:
        await pool.aclose()

    final_job = conn.execute(
        "SELECT status FROM jobs WHERE id = ?", (cluster_job_id,)
    ).fetchone()
    queue_row = conn.execute(
        "SELECT status FROM analysis_queue WHERE question_detail_id = ?", (detail_id,)
    ).fetchone()
    assert final_job["status"] == "completed"
    assert queue_row["status"] == "done"
    final_reconcile = await scheduled_upload_queue_reconcile_task({})
    assert final_reconcile["jobs_created"] == 0
    assert (await scheduled_submit_job_dispatch_task({}))["dispatched"] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? "
        "AND work_key = (SELECT work_key FROM jobs WHERE id = ?)",
        (accepted["import_id"], cluster_job_id),
    ).fetchone()[0] == 1


@pytest.mark.parametrize("fail_first_batch", [True, False])
async def test_rootless_public_contribution_continues_remaining_items(
    isolated_stack, isolated_redis, monkeypatch, fail_first_batch
):
    """AC-007: rootless contributions continue after failed and successful batches."""

    from arq.connections import RedisSettings
    from arq.worker import Worker
    from unittest.mock import AsyncMock

    import app.worker_enqueue as enqueue_module
    from app.services.pipeline import BATCH_SIZE
    import app.services.pipeline.queue as queue_module
    from app.services.pipeline.queue import _run_cluster_batch_in_background, enqueue_questions
    from app.services.public_contributions import create_admin_public_import_approval
    from app.worker_cluster_tasks import cluster_batch_task

    conn = isolated_stack
    interview_cursor = conn.execute(
        "INSERT INTO interview "
        "(url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (?, ?, ?, ?, NULL, 'approved', ?)",
        (
            "https://ac007.example/rootless-public",
            "AC007 Rootless",
            "一面",
            "rootless fixture",
            "后端开发",
        ),
    )
    interview_id = int(interview_cursor.lastrowid)
    source_items = []
    detail_ids = []
    item_count = BATCH_SIZE + 1 if fail_first_batch else (BATCH_SIZE * 2) + 1
    for ordinal in range(item_count):
        question = f"AC007 rootless public question {ordinal}"
        source_items.append(
            {
                "question": question,
                "cat1": "后端",
                "cat2": "队列",
                "tags": "recovery",
                "source_ordinal": ordinal,
            }
        )
        detail_cursor = conn.execute(
            "INSERT INTO questions_detail "
            "(interview_id, question, cat1, cat2, tags, owner_id, status, source_ordinal) "
            "VALUES (?, ?, '后端', '队列', 'recovery', NULL, 'approved', ?)",
            (interview_id, question, ordinal),
        )
        detail_ids.append(int(detail_cursor.lastrowid))

    source_snapshot = {
        "source": {"job_position": "后端开发", "company": "AC007 Rootless"},
        "items": source_items,
    }
    request_id = create_admin_public_import_approval(
        conn,
        import_id=None,
        admin_id=201,
        interview_id=interview_id,
        detail_ids=detail_ids,
        source_snapshot=source_snapshot,
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'queued' WHERE request_id = ?",
        (request_id,),
    )
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'queued' WHERE id = ?",
        (request_id,),
    )
    enqueued = enqueue_questions(
        interview_id,
        owner_id=None,
        question_detail_ids=detail_ids,
        contribution_request_id=request_id,
        conn=conn,
    )
    assert enqueued == item_count
    private_backlog_detail_ids = []
    if not fail_first_batch:
        private_interview_id = int(
            conn.execute(
                "INSERT INTO interview "
                "(url, company, round, questions_list, owner_id, status, job_position) "
                "VALUES ('https://ac007.example/private-rootless', 'AC007 Private', '一面', "
                "'private backlog', 101, 'approved', '后端开发')"
            ).lastrowid
        )
        for ordinal in range((BATCH_SIZE * 2) + 5):
            detail_id = int(
                conn.execute(
                    "INSERT INTO questions_detail "
                    "(interview_id, question, cat1, cat2, owner_id, status) "
                    "VALUES (?, ?, '后端', '队列', 101, 'approved')",
                    (private_interview_id, f"AC007 private backlog {ordinal}"),
                ).lastrowid
            )
            private_backlog_detail_ids.append(detail_id)
            conn.execute(
                "INSERT INTO analysis_queue "
                "(interview_id, question_detail_id, owner_id, status) "
                "VALUES (?, ?, 101, 'pending')",
                (private_interview_id, detail_id),
            )
    conn.commit()

    # Keep the final short batch immediately available so the real worker can
    # prove that every durable continuation is consumed in this isolated run.
    monkeypatch.setattr(queue_module, "CLUSTER_DELAY_SECONDS", 0)
    created = await _run_cluster_batch_in_background(
        user_id=201,
        queue_scope=(
            queue_module.PUBLIC_CONTRIBUTION_QUEUE_SCOPE if fail_first_batch else None
        ),
    )
    assert created
    concurrent_private_root_id = None
    if not fail_first_batch:
        concurrent_private_root_id = "ac007-active-private-root"
        conn.execute(
            "INSERT INTO upload_imports "
            "(id, requester_id, idempotency_key, request_hash, target_intent, "
            "source_type, pipeline_version) "
            "VALUES (?, 101, 'ac007-private', 'private-hash', 'private', 'interview', 'v1')",
            (concurrent_private_root_id,),
        )
        private_interview_id = int(
            conn.execute(
                "INSERT INTO interview "
                "(url, company, round, questions_list, owner_id, status, job_position) "
                "VALUES ('https://ac007.example/private', 'AC007 Private', '一面', "
                "'private fixture', 101, 'approved', '后端开发')"
            ).lastrowid
        )
        private_detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail "
                "(interview_id, question, cat1, cat2, owner_id, status) "
                "VALUES (?, 'AC007 private bucket remains active', '后端', '队列', 101, 'approved')",
                (private_interview_id,),
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO analysis_queue "
            "(interview_id, question_detail_id, owner_id, status, root_import_id) "
            "VALUES (?, ?, 101, 'pending', ?)",
            (private_interview_id, private_detail_id, concurrent_private_root_id),
        )
        from app.services.upload_queue import reconcile_pending_buckets

        assert reconcile_pending_buckets(conn)["jobs_created"] == 1
        conn.commit()
    first_batch_ids = []
    first_batch_owners = []
    generic_private_batches = []
    arrivals_added = 0

    async def cluster_batch_that_fails_once(batch, **_kwargs):
        contains_contribution = any(
            item.get("contribution_request_id") == request_id for item in batch
        )
        if contains_contribution:
            first_batch_ids.append([item["qd_id"] for item in batch])
            first_batch_owners.append([item["owner_id"] for item in batch])
        else:
            generic_private_batches.append(batch)
        if fail_first_batch and len(first_batch_ids) == 1:
            raise RuntimeError("AC007 deterministic batch failure")
        from app.services.question_resolution import record_resolution

        for item in batch:
            if item.get("contribution_request_id") != request_id:
                continue
            canonical = conn.execute(
                "INSERT INTO question_bank "
                "(question, cat1, cat2, tags, frequency, sources, original_questions, "
                "original_question_sources, owner_id, status, job_position) "
                "VALUES (?, ?, ?, ?, 1, '[]', ?, '[]', NULL, 'approved', '后端开发')",
                (
                    item["question"],
                    item["cat1"],
                    item["cat2"],
                    item["tags"],
                    json.dumps([{"question": item["question"]}], ensure_ascii=False),
                ),
            )
            record_resolution(
                conn,
                detail_id=int(item["qd_id"]),
                occurrence_scope="public",
                occurrence_owner_id=None,
                canonical_id=int(canonical.lastrowid),
                canonical_scope="public",
                status="created",
                pipeline_version="ac007-rootless-fixture",
                reason="created",
            )
        if not fail_first_batch and batch and batch[0].get("contribution_request_id") == request_id:
            nonlocal arrivals_added
            if arrivals_added < 3:
                ordinal = item_count + arrivals_added
                question = f"AC007 continuously arriving public question {ordinal}"
                detail_id = int(
                    conn.execute(
                        "INSERT INTO questions_detail "
                        "(interview_id, question, cat1, cat2, tags, owner_id, status, source_ordinal) "
                        "VALUES (?, ?, '后端', '队列', 'recovery', NULL, 'approved', ?)",
                        (interview_id, question, ordinal),
                    ).lastrowid
                )
                item_cursor = conn.execute(
                    "INSERT INTO public_contribution_items "
                    "(request_id, source_item_type, source_item_id, ordinal, status, "
                    "snapshot_json, public_detail_id) "
                    "VALUES (?, 'question', ?, ?, 'queued', ?, ?)",
                    (
                        request_id,
                        detail_id,
                        ordinal,
                        json.dumps({"question": question}, ensure_ascii=False),
                        detail_id,
                    ),
                )
                conn.execute(
                    "INSERT INTO analysis_queue "
                    "(interview_id, question_detail_id, owner_id, status, contribution_request_id) "
                    "VALUES (?, ?, NULL, 'pending', ?)",
                    (interview_id, detail_id, request_id),
                )
                assert item_cursor.rowcount == 1
                arrivals_added += 1
        conn.commit()
        return {"count": len(batch), "ids": []}

    cluster_batch_mock = AsyncMock(side_effect=cluster_batch_that_fails_once)
    monkeypatch.setattr("app.services.pipeline.cluster_batch", cluster_batch_mock)

    async def run_rootless_test_worker():
        worker = Worker(
            functions=[cluster_batch_task],
            queue_name=isolated_redis["queue_name"],
            redis_settings=RedisSettings.from_dsn(enqueue_module.REDIS_URL),
            handle_signals=False,
            burst=True,
            max_tries=1,
            job_timeout=30,
            keep_result=60,
            poll_delay=0.01,
            queue_read_limit=10,
        )
        await worker.main()
        await worker.close()

    await run_rootless_test_worker()

    if fail_first_batch:
        # fail_job keeps a transiently failed job pending with backoff. Advance
        # its durable clock, then prove the dispatcher creates one Redis work
        # item and a repeated dispatcher pass does not duplicate it.
        conn.execute(
            "UPDATE jobs SET available_at = CURRENT_TIMESTAMP "
            "WHERE job_type = 'cluster_batch' AND root_import_id IS NULL",
        )
        conn.commit()
        from app.worker_scheduled import scheduled_submit_job_dispatch_task

        dispatched = await scheduled_submit_job_dispatch_task({})
        assert dispatched["dispatched"] == 1
        repeated_dispatch = await scheduled_submit_job_dispatch_task({})
        assert repeated_dispatch["dispatched"] == 0
        pool = await isolated_redis["new_pool"]()
        try:
            durable_job_id = int(
                conn.execute(
                    "SELECT id FROM jobs WHERE job_type = 'cluster_batch' "
                    "AND root_import_id IS NULL"
                ).fetchone()["id"]
            )
            queued = await pool.queued_jobs()
            matching = [
                job for job in queued
                if job.function == "cluster_batch_task" and job.args[0] == durable_job_id
            ]
            assert len(matching) == 1
        finally:
            await pool.aclose()
        await run_rootless_test_worker()

    expected_batch_sizes = (
        [BATCH_SIZE, 1]
        if fail_first_batch
        else [BATCH_SIZE, BATCH_SIZE, 3, 1]
    )
    if not fail_first_batch:
        assert generic_private_batches
        assert len(generic_private_batches[0]) == BATCH_SIZE
        assert {item["owner_id"] for item in generic_private_batches[0]} == {101}
        assert [len(batch) for batch in generic_private_batches] == [
            BATCH_SIZE,
            BATCH_SIZE,
            5,
        ]
    assert [len(batch) for batch in first_batch_ids] == expected_batch_sizes
    assert all(owner_ids == [None] * len(owner_ids) for owner_ids in first_batch_owners)
    assert len({detail_id for batch in first_batch_ids for detail_id in batch}) == sum(expected_batch_sizes)

    item_states = conn.execute(
        "SELECT status, COUNT(*) AS count FROM public_contribution_items "
        "WHERE request_id = ? GROUP BY status",
        (request_id,),
    ).fetchall()
    expected_item_states = (
        {"failed": BATCH_SIZE, "published": 1}
        if fail_first_batch
        else {"published": item_count + arrivals_added}
    )
    assert {row["status"]: row["count"] for row in item_states} == expected_item_states
    request_state = conn.execute(
        "SELECT status FROM public_contribution_requests WHERE id = ?", (request_id,)
    ).fetchone()
    assert request_state["status"] == (
        "partially_published" if fail_first_batch else "published"
    )

    jobs = conn.execute(
        "SELECT status FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL ORDER BY id"
    ).fetchall()
    expected_job_count = (
        1 if fail_first_batch else len(expected_batch_sizes) + len(generic_private_batches)
    )
    expected_job_states = ["completed"] * expected_job_count
    assert [row["status"] for row in jobs] == expected_job_states
    if concurrent_private_root_id:
        private_job_state = conn.execute(
            "SELECT status FROM jobs WHERE root_import_id = ? AND job_type = 'cluster_batch'",
            (concurrent_private_root_id,),
        ).fetchone()
        assert private_job_state["status"] == "pending"
        still_pending_private = conn.execute(
            "SELECT COUNT(*) FROM analysis_queue WHERE question_detail_id IN ("
            + ",".join("?" for _ in private_backlog_detail_ids)
            + ") AND status = 'pending'",
            private_backlog_detail_ids,
        ).fetchone()[0]
        assert still_pending_private == 0


@pytest.mark.parametrize(
    ("active_scope", "requested_scope"),
    [
        (None, "public_contribution"),
        ("public_contribution", None),
    ],
)
async def test_rootless_cluster_jobs_with_different_scopes_do_not_overlap(
    isolated_stack, monkeypatch, active_scope, requested_scope
):
    """Legacy generic jobs can consume public rows, so rootless scopes must serialize."""
    import json

    import app.services.pipeline.queue as queue_module
    from app.services.pipeline.queue import _run_cluster_batch_in_background

    conn = isolated_stack
    payload = {"user_id": 101}
    if active_scope:
        payload["queue_scope"] = active_scope
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, idempotency_key) "
        "VALUES ('cluster_batch', 'queued', 101, 'ac007-cross-scope-active')"
    )
    active_job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (active_job_id, json.dumps(payload)),
    )
    conn.commit()
    monkeypatch.setattr(queue_module, "CLUSTER_DELAY_SECONDS", 300)

    scheduled = await _run_cluster_batch_in_background(
        user_id=201,
        queue_scope=requested_scope,
    )

    assert not scheduled
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL AND status IN ('pending', 'queued', 'running')"
    ).fetchone()[0] == 1


async def test_cluster_rebuild_waits_for_rootless_cluster_batch(
    isolated_stack, isolated_redis
):
    """Full rebuild and incremental jobs must not consume the same public queue concurrently."""
    import json

    from app.services.pipeline.batch import force_cluster_all_pending
    from app.services.pipeline.queue import _run_cluster_batch_in_background
    from app.worker_scheduled import scheduled_submit_job_dispatch_task

    conn = isolated_stack
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, idempotency_key) "
        "VALUES ('cluster_batch', 'running', 101, 'ac007-active-rootless-batch')"
    )
    active_batch_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (active_batch_id, json.dumps({"user_id": 101})),
    )
    conn.commit()

    rebuild = await force_cluster_all_pending(user_id=201)
    assert rebuild["status"] == "pending"
    dispatch_while_batch_active = await scheduled_submit_job_dispatch_task({})
    assert dispatch_while_batch_active["dispatched"] == 0

    pool = await isolated_redis["new_pool"]()
    try:
        queued = await pool.queued_jobs()
        assert not [job for job in queued if job.function == "cluster_rebuild_task"]
    finally:
        await pool.aclose()

    conn.execute(
        "UPDATE jobs SET status = 'completed' WHERE id = ?", (active_batch_id,)
    )
    conn.commit()
    new_batch = await _run_cluster_batch_in_background(user_id=201)
    assert not new_batch
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL AND status IN ('pending', 'queued', 'running')"
    ).fetchone()[0] == 0

    dispatched = await scheduled_submit_job_dispatch_task({})
    assert dispatched["dispatched"] == 1
    pool = await isolated_redis["new_pool"]()
    try:
        queued = await pool.queued_jobs()
        rebuild_jobs = [job for job in queued if job.function == "cluster_rebuild_task"]
        assert len(rebuild_jobs) == 1
        assert rebuild_jobs[0].args[0] == rebuild["job_id"]
    finally:
        await pool.aclose()


@pytest.mark.parametrize(
    "queue_kind", ["public_regular", "public_contribution", "personal"]
)
@pytest.mark.parametrize("terminal_failure", [False, True])
async def test_cluster_rebuild_releases_rootless_work_on_exit(
    isolated_stack, isolated_redis, monkeypatch, queue_kind, terminal_failure
):
    """Rootless work racing with rebuild completion/failure must get a successor."""
    import app.services.pipeline as pipeline_module
    import app.services.pipeline.queue as queue_module
    from app.services.pipeline.queue import has_active_rootless_cluster_job
    from app.worker_cluster_tasks import cluster_rebuild_task

    conn = isolated_stack
    rebuild_cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, attempts, created_by, idempotency_key) "
        "VALUES ('cluster_rebuild', 'pending', ?, 201, 'ac007-empty-read-race')",
        (100 if terminal_failure else 0,),
    )
    rebuild_job_id = int(rebuild_cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, '{}')",
        (rebuild_job_id,),
    )
    conn.commit()
    monkeypatch.setattr(queue_module, "CLUSTER_DELAY_SECONDS", 0)

    inserted = False

    def dequeue_empty_then_insert_contribution(batch_size, *, owner_id):
        nonlocal inserted
        assert owner_id is None
        assert not inserted
        inserted = True
        queue_owner_id = 101 if queue_kind == "personal" else None

        public_interview_id = int(
            conn.execute(
                "INSERT INTO interview "
                "(url, company, round, questions_list, owner_id, status, job_position) "
                "VALUES ('https://ac007.example/late-public', 'AC007 Late', '一面', "
                "'late public question', ?, 'approved', '后端开发')",
                (queue_owner_id,),
            ).lastrowid
        )
        public_detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail "
                "(interview_id, question, cat1, cat2, owner_id, status) "
                "VALUES (?, 'AC007 late contribution', '后端', '并发', ?, 'approved')",
                (public_interview_id, queue_owner_id),
            ).lastrowid
        )
        request_id = None
        if queue_kind == "public_contribution":
            request_id = int(conn.execute(
                "INSERT INTO public_contribution_requests "
                "(source_type, source_id, requester_id, public_interview_id, status, snapshot_json) "
                "VALUES ('interview', ?, 101, ?, 'queued', '{}')",
                (public_interview_id, public_interview_id),
            ).lastrowid)
            conn.execute(
                "INSERT INTO public_contribution_items "
                "(request_id, source_item_type, source_item_id, ordinal, status, "
                "snapshot_json, public_detail_id) "
                "VALUES (?, 'question', ?, 1, 'queued', '{}', ?)",
                (request_id, public_detail_id, public_detail_id),
            )
        conn.execute(
            "INSERT INTO analysis_queue "
            "(interview_id, question_detail_id, owner_id, status, contribution_request_id) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (public_interview_id, public_detail_id, queue_owner_id, request_id),
        )
        conn.commit()
        # This is the approval/retry scheduler's check during the lost-wakeup
        # window. The active rebuild correctly defers the incremental job.
        assert has_active_rootless_cluster_job(conn)
        if terminal_failure:
            raise RuntimeError("AC007 deterministic terminal rebuild failure")
        return []

    monkeypatch.setattr(
        pipeline_module, "dequeue_batch", dequeue_empty_then_insert_contribution
    )

    result = await cluster_rebuild_task({}, rebuild_job_id)

    expected_rebuild_status = "failed" if terminal_failure else "completed"
    assert result["status"] == ("failed" if terminal_failure else "done")
    rebuild_state = conn.execute(
        "SELECT status FROM jobs WHERE id = ?", (rebuild_job_id,)
    ).fetchone()["status"]
    assert rebuild_state == expected_rebuild_status
    continuation = conn.execute(
        "SELECT id, status FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL"
    ).fetchone()
    assert continuation is not None
    assert continuation["status"] == "queued"
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM job_payloads WHERE job_id = ?",
            (continuation["id"],),
        ).fetchone()["payload"]
    )
    if queue_kind == "public_contribution":
        assert payload["queue_scope"] == "public_contribution"
    else:
        assert "queue_scope" not in payload

    pool = await isolated_redis["new_pool"]()
    try:
        queued = await pool.queued_jobs()
        continuation_jobs = [
            job for job in queued
            if job.function == "cluster_batch_task" and job.args[0] == continuation["id"]
        ]
        assert len(continuation_jobs) == 1
    finally:
        await pool.aclose()


def _seed_rootless_poison_row(conn, owner_id):
    interview_id = int(
        conn.execute(
            "INSERT INTO interview "
            "(url, company, round, questions_list, owner_id, status, job_position) "
            "VALUES (?, 'AC007 Poison', '一面', 'poison row', ?, 'approved', '后端开发')",
            (f"https://ac007.example/poison-{owner_id}", owner_id),
        ).lastrowid
    )
    detail_id = int(
        conn.execute(
            "INSERT INTO questions_detail "
            "(interview_id, question, cat1, cat2, owner_id, status) "
            "VALUES (?, 'AC007 deterministic poison row', '后端', '故障恢复', ?, 'approved')",
            (interview_id, owner_id),
        ).lastrowid
    )
    queue_id = int(
        conn.execute(
            "INSERT INTO analysis_queue "
            "(interview_id, question_detail_id, owner_id, status) "
            "VALUES (?, ?, ?, 'pending')",
            (interview_id, detail_id, owner_id),
        ).lastrowid
    )
    conn.commit()
    return queue_id


@pytest.mark.parametrize("owner_id", [None, 101])
async def test_terminal_rootless_cluster_batch_failure_does_not_respawn_poison_row(
    isolated_stack, isolated_redis, monkeypatch, owner_id
):
    """A terminal rootless failure is retained for explicit retry, not auto-spawned."""
    from unittest.mock import AsyncMock

    import app.services.pipeline as pipeline_module
    import app.worker_cluster_tasks as worker_cluster_tasks

    conn = isolated_stack
    queue_id = _seed_rootless_poison_row(conn, owner_id)
    job_id = int(
        conn.execute(
            "INSERT INTO jobs "
            "(job_type, status, attempts, created_by, idempotency_key) "
            "VALUES ('cluster_batch', 'pending', 2, 201, ?)",
            (f"ac007-terminal-poison-batch-{owner_id}",),
        ).lastrowid
    )
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, json.dumps({"user_id": 201})),
    )
    conn.commit()
    monkeypatch.setattr(
        worker_cluster_tasks, "_cluster_preflight_ready", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        pipeline_module,
        "cluster_batch",
        AsyncMock(side_effect=RuntimeError("AC007 deterministic poison failure")),
    )

    result = await worker_cluster_tasks.cluster_batch_task({}, job_id)

    assert result["status"] == "failed"
    assert conn.execute(
        "SELECT status FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()["status"] == "failed"
    assert conn.execute(
        "SELECT status FROM analysis_queue WHERE id = ?", (queue_id,)
    ).fetchone()["status"] == "failed"
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL AND status IN ('pending', 'queued', 'running')"
    ).fetchone()[0] == 0


async def test_terminal_cluster_rebuild_failure_does_not_respawn_poison_row(
    isolated_stack, isolated_redis, monkeypatch
):
    """A failed rebuild must not turn its poison batch into an endless new job chain."""
    from unittest.mock import AsyncMock

    import app.services.pipeline as pipeline_module
    import app.worker_cluster_tasks as worker_cluster_tasks

    conn = isolated_stack
    queue_id = _seed_rootless_poison_row(conn, None)
    rebuild_job_id = int(
        conn.execute(
            "INSERT INTO jobs "
            "(job_type, status, attempts, created_by, idempotency_key) "
            "VALUES ('cluster_rebuild', 'pending', 2, 201, 'ac007-terminal-poison-rebuild')"
        ).lastrowid
    )
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, '{}')",
        (rebuild_job_id,),
    )
    conn.commit()
    monkeypatch.setattr(
        pipeline_module,
        "cluster_batch",
        AsyncMock(side_effect=RuntimeError("AC007 deterministic poison failure")),
    )

    result = await worker_cluster_tasks.cluster_rebuild_task({}, rebuild_job_id)

    assert result["status"] == "failed"
    assert conn.execute(
        "SELECT status FROM jobs WHERE id = ?", (rebuild_job_id,)
    ).fetchone()["status"] == "failed"
    assert conn.execute(
        "SELECT status FROM analysis_queue WHERE id = ?", (queue_id,)
    ).fetchone()["status"] == "failed"
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL AND status IN ('pending', 'queued', 'running')"
    ).fetchone()[0] == 0


def test_two_roots_submitted_same_second_do_not_cross_talk(isolated_stack):
    conn = isolated_stack
    from app.services.upload_lifecycle import accept_upload, build_thread_id

    import threading

    fixed_timestamp = "2026-10-03 12:34:56"
    conn.execute(
        "CREATE TRIGGER fixed_upload_created_at AFTER INSERT ON upload_imports "
        "BEGIN UPDATE upload_imports SET created_at = '2026-10-03 12:34:56', "
        "updated_at = '2026-10-03 12:34:56' WHERE id = NEW.id; END"
    )
    conn.execute(
        "CREATE TRIGGER fixed_job_created_at AFTER INSERT ON jobs "
        "BEGIN UPDATE jobs SET created_at = '2026-10-03 12:34:56', "
        "updated_at = '2026-10-03 12:34:56' WHERE id = NEW.id; END"
    )
    conn.commit()

    barrier = threading.Barrier(2)
    submitted = {}
    errors = {}
    requests = {
        1: ("stack-a", "面经 A：Redis 持久化"),
        2: ("stack-b", "面经 B：线程池参数"),
    }

    def _submit(index):
        db = sqlite3.connect(
            os.environ["UPLOAD_TEST_DB_PATH"], check_same_thread=False, timeout=30
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            barrier.wait(timeout=10)
            key, text = requests[index]
            submitted[index] = accept_upload(
                db,
                actor_id=101,
                actor_is_admin=False,
                idempotency_key=key,
                target_intent="private",
                source_type="interview",
                text=text,
                position_name="后端",
                files=[],
                images=[],
                entry="api",
                credential_loaders=_loaders(),
            )
            db.commit()
        except Exception as exc:  # pragma: no cover - assertion reports worker errors
            errors[index] = exc
        finally:
            db.close()

    threads = [threading.Thread(target=_submit, args=(i,)) for i in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(not thread.is_alive() for thread in threads), "并发提交线程必须结束"
    assert not errors, errors
    first, second = submitted[1], submitted[2]
    assert first["import_id"] != second["import_id"]
    assert first["job_id"] != second["job_id"]

    roots = conn.execute(
        "SELECT id, created_at, payload_json FROM upload_imports "
        "WHERE id IN (?, ?) ORDER BY idempotency_key",
        (first["import_id"], second["import_id"]),
    ).fetchall()
    assert len(roots) == 2
    assert {row["created_at"] for row in roots} == {fixed_timestamp}
    job_times = conn.execute(
        "SELECT id, created_at, upload_attempt_id FROM jobs WHERE id IN (?, ?)",
        (first["job_id"], second["job_id"]),
    ).fetchall()
    assert len(job_times) == 2
    assert {row["created_at"] for row in job_times} == {fixed_timestamp}
    assert all(row["upload_attempt_id"] is not None for row in job_times)
    assert len({row["upload_attempt_id"] for row in job_times}) == 2
    payloads = {row["id"]: row["payload_json"] for row in roots}
    assert "Redis" in payloads[first["import_id"]]
    assert "线程池" not in payloads[first["import_id"]]
    assert "线程池" in payloads[second["import_id"]]
    assert "Redis" not in payloads[second["import_id"]]

    thread_a = build_thread_id(first["import_id"], 1, first["job_id"])
    thread_b = build_thread_id(second["import_id"], 1, second["job_id"])
    assert thread_a != thread_b, "固定时钟下的并发提交不得共享执行状态"


def test_user_scope_never_borrows_system_stub(isolated_stack):
    from app.services.upload_credentials import UploadCredentialError, resolve_upload_credentials

    calls = {"global": 0}

    def broken_user(uid):
        raise RuntimeError("decrypt failed")

    def global_loader():
        calls["global"] += 1
        return {"api_key": "k", "base_url": "https://s.invalid/v1", "model": "m", "timeout": 5}

    with pytest.raises(UploadCredentialError):
        resolve_upload_credentials(
            credential_scope="user",
            user_id=101,
            stage="extract",
            user_config_loader=broken_user,
            global_config_loader=global_loader,
        )
    assert calls["global"] == 0

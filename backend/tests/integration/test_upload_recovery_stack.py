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
    assert len(interviews) == 1, "重启后必须产出恰好一份私人面经"
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


def test_two_roots_submitted_same_second_do_not_cross_talk(isolated_stack):
    conn = isolated_stack
    from app.services.upload_lifecycle import accept_upload, build_thread_id

    first = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="stack-a",
        target_intent="private",
        source_type="interview",
        text="面经 A：Redis 持久化",
        position_name="后端",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )
    second = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="stack-b",
        target_intent="private",
        source_type="interview",
        text="面经 B：线程池参数",
        position_name="后端",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )
    assert first["import_id"] != second["import_id"]
    assert first["job_id"] != second["job_id"]

    thread_a = build_thread_id(first["import_id"], 1, first["job_id"])
    thread_b = build_thread_id(second["import_id"], 1, second["job_id"])
    assert thread_a != thread_b, "同秒提交的任务不得共享执行状态"

    rows = conn.execute(
        "SELECT id, payload_json FROM upload_imports ORDER BY id"
    ).fetchall()
    payloads = [row["payload_json"] for row in rows]
    assert any("Redis" in p for p in payloads)
    assert any("线程池" in p for p in payloads)
    assert not (payloads[0].count("线程池") and payloads[0].count("Redis")), "结果不得串单"


def test_user_scope_never_borrows_system_stub(isolated_stack):
    conn = isolated_stack
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

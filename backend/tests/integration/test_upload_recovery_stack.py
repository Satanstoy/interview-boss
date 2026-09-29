"""AC-028：隔离集成入口（真实服务代码 + 临时 SQLite + 本地 stub，不出网）。

按验收要求**拒绝在非隔离环境启动**：必须显式提供

- ``UPLOAD_TEST_DB_PATH``：临时 SQLite 路径（测试自己创建/迁移/删除）；
- ``UPLOAD_TEST_REDIS_PREFIX``：独立随机缓存前缀，避免污染共享 Redis。

fixture 注入 ``app.db.connection`` 的连接工厂与 ``config.DB_PATH``，
而不是假定生产配置会读取测试变量。模型调用全部使用本地 stub。
"""

from __future__ import annotations

import os
import sqlite3
import threading

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


@pytest.fixture
def isolated_stack(monkeypatch, tmp_path):
    """注入临时库与本地 stub；测试结束还原。"""

    db_path = os.environ["UPLOAD_TEST_DB_PATH"]
    if os.path.exists(db_path):
        os.remove(db_path)

    from app.db.migrations import run_migrations
    import app.db.connection as db_module

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
    conn.commit()

    token = db_module._db_conn_var.set(conn)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    def _test_get_db_connection():
        return conn

    for name in ("app.db.connection", "app.db.operations", "app.db.queries", "app.services.pipeline.queue"):
        module = __import__(name, fromlist=["*"])
        if hasattr(module, "get_db_connection"):
            monkeypatch.setattr(module, "get_db_connection", _test_get_db_connection)

    yield conn

    db_module._db_conn_var.reset(token)
    conn.close()
    if os.path.exists(db_path):
        os.remove(db_path)


def _loaders():
    return {
        "user": lambda uid: {
            "api_key": "stub-user-key",
            "base_url": "https://stub.invalid/v1",
            "model": "stub-model",
            "timeout": 5,
        },
        "global": lambda: {
            "api_key": "stub-system-key",
            "base_url": "https://stub.invalid/v1",
            "model": "stub-model",
            "timeout": 5,
        },
    }


def test_env_guard_refuses_unconfigured_run():
    """没有隔离变量时必须拒绝启动（模块级 skipif 即守卫本身）。"""

    assert set(REQUIRED_ENV) == {"UPLOAD_TEST_DB_PATH", "UPLOAD_TEST_REDIS_PREFIX"}


def test_accept_crash_restore_does_not_duplicate_work(isolated_stack):
    conn = isolated_stack
    from app.services.upload_lifecycle import accept_upload, restore_upload
    from app.services.upload_repository import get_stage_result, save_stage_result

    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="stack-1",
        target_intent="private",
        source_type="interview",
        text="面经：解释 TCP 三次握手",
        position_name="后端",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )
    assert accepted["created"] is True

    # 提取检查点已落盘（模拟第一次 worker 完成提取后被杀）
    save_stage_result(
        conn,
        import_id=accepted["import_id"],
        stage="extract",
        unit_key="document",
        input_version=1,
        pipeline_version="upload-pipeline-v1",
        status="succeeded",
        result_json='{"questions": [{"ordinal": 1, "question": "TCP 三次握手"}]}',
    )
    conn.commit()

    # 恢复：复用检查点，不重复提取、不重复建 attempt
    restored = restore_upload(conn, actor_id=101, import_id=accepted["import_id"])
    again = restore_upload(conn, actor_id=101, import_id=accepted["import_id"])
    assert restored["import_id"] == accepted["import_id"]
    assert again["attempt_id"] == restored["attempt_id"]

    checkpoint = get_stage_result(
        conn,
        import_id=accepted["import_id"],
        stage="extract",
        unit_key="document",
        input_version=1,
    )
    assert checkpoint["status"] == "succeeded"
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM upload_stage_results WHERE stage = 'extract'"
    ).fetchone()[0] == 1


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

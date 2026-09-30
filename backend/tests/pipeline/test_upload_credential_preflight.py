"""AC-004 / UR-004：提交前配置预检的默认路径（不接受注入 loader 的替代验证）。

验收矩阵（acceptance.md AC-004）要求证明**生产默认解析路径**的负向反例：
数据库中 U1 没有个人配置而 global 配置有效时，真实 ``resolve_upload_credentials``
（``credential_scope="user"``，走默认读取器）与实际上传入口都返回 user scope 的
``needs_action``，绝不读取/使用 global 模型。只给 resolver 注入
``user_config_loader`` 的单元测试不够，因为它绕过了默认配置读取器。

本文件直接构造真实 test_db：U1 无 ``user_llm_config`` 行、global 配置有效，
断言：
- strict user 读取器返回 None，而通用读取器会回退 global（对照）；
- resolver 默认路径 user scope → ``MODEL_CONFIG_MISSING``（scope=user），
  不调用 global loader；
- accept_upload 真实入口在 global 有效时仍把根任务置 ``needs_action``，
  不创建任何业务处理 job（不派发提取/分类通常模型工作）；
- 配置好 user 后从同一 root 恢复：资格预检通过、创建首个业务 job（AC-004 的
  “修复正确 scope 后从同一 root 恢复，只处理未完成阶段”服务层）。
"""

from __future__ import annotations

import sqlite3

from unittest.mock import patch

import pytest

from app.db.migrations import run_migrations


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    # global 配置有效：确定性 user_profile + env 兜底
    for key, value in (
        ("llm_api_key", "global-secret-key"),
        ("llm_base_url", "https://system.example.com/v1"),
        ("llm_model", "system-model"),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO user_profile (key, value) VALUES (?, ?)", (key, value)
        )
    conn.commit()
    return conn


def _resolve_default(conn, *, credential_scope="user", user_id=101, stage="extract"):
    """调用 resolver 的**默认路径**（不注入 loader）。"""

    # 让 config 读取器走测试连接
    def _load_for_core():
        import app.db.connection as db_module

        token = db_module._db_conn_var.set(conn)
        try:
            from app.services.upload_credentials import resolve_upload_credentials

            return resolve_upload_credentials(
                credential_scope=credential_scope,
                user_id=user_id if credential_scope == "user" else None,
                stage=stage,
            )
        finally:
            db_module._db_conn_var.reset(token)

    return _load_for_core()


def _accept(conn, **overrides):
    """调用 accept_upload，并把默认凭据读取器指向测试连接（真实默认路径）。"""

    import app.db.connection as db_module
    from app.services.upload_lifecycle import accept_upload

    token = db_module._db_conn_var.set(conn)
    params = dict(
        actor_id=101,
        actor_is_admin=False,
        target_intent="private",
        source_type="interview",
        text="面经：解释 TCP 三次握手",
        entry="api",
    )
    params.update(overrides)
    try:
        return accept_upload(conn, **params)
    finally:
        db_module._db_conn_var.reset(token)


def test_strict_loader_returns_none_while_generic_falls_back():
    """U1 无个人配置 + global 有效：通用读取器回退 global，strict 读取器返回 None。"""

    conn = _db()
    from app.core.config import get_strict_user_llm_config, get_user_llm_config

    def _load(fn):
        import app.db.connection as db_module

        token = db_module._db_conn_var.set(conn)
        try:
            return fn(101)
        finally:
            db_module._db_conn_var.reset(token)

    generic = _load(get_user_llm_config)
    assert generic is not None and generic["api_key"] == "global-secret-key"
    strict = _load(get_strict_user_llm_config)
    assert strict is None, "strict 读取器不得回退 global"
    conn.close()


def test_default_user_scope_blocks_when_global_valid():
    """AC-004 负向反例：真实默认路径 user scope 在 global 有效时仍阻断。"""

    from app.services.upload_credentials import UploadCredentialError

    conn = _db()
    with pytest.raises(UploadCredentialError) as exc:
        _resolve_default(conn, credential_scope="user", user_id=101)
    assert exc.value.code == "MODEL_CONFIG_MISSING"
    assert exc.value.scope == "user"
    assert exc.value.action == "configure_user_model"
    conn.close()


def test_default_global_scope_succeeds_with_system_config():
    """对照：global scope 用系统配置解析成功（不走用户私钥）。"""

    conn = _db()
    resolved = _resolve_default(conn, credential_scope="global", user_id=101)
    assert resolved.scope == "global"
    assert resolved.payer_type == "system"
    assert resolved.api_key == "global-secret-key"
    assert "api_key" not in resolved.model_dump(), "快照不暴露 Key"
    conn.close()


def test_accept_entry_blocks_on_missing_user_config_with_valid_global():
    """实际上传入口：U1 缺个人 Key 而 global 有效 → needs_action，无业务 job。"""

    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    try:
        from app.services.upload_lifecycle import accept_upload

        result = _accept(conn, idempotency_key="k-1")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    assert result["created"] is True
    assert result["error"] is not None
    assert result["error"]["code"] == "MODEL_CONFIG_MISSING"
    assert result["error"]["scope"] == "user"
    assert result["status"] == "needs_action"
    # 不允许任何模型工作被创建（提取/分类/聚类的业务 job 都不得存在）
    jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert jobs == 0, f"配置缺失时不得派发业务 job，实际 {jobs}"
    conn.close()


def test_accept_entry_blocks_share_when_global_ok_but_user_missing():
    """普通用户 share：global 有效、私人暂存需 user → 预检失败同样 needs_action。"""

    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _accept(conn, idempotency_key="k-share-1", target_intent="share")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    assert result["status"] == "needs_action"
    assert result["error"]["code"] == "MODEL_CONFIG_MISSING"
    assert result["error"]["scope"] == "user"
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_configured_user_then_accept_creates_first_business_job():
    """修复正确 scope 后从同一入口提交：预检通过，创建首个业务 job。"""

    conn = _db()
    # 用户配置好个人模型（加密或明文均可——decrypt 容错）
    conn.execute(
        "INSERT INTO user_llm_config (user_id, api_key, base_url, model) "
        "VALUES (101, 'user-key', 'https://user.example.com/v1', 'user-model')"
    )
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _accept(conn, idempotency_key="k-2")
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    assert result["error"] is None
    assert result["status"] in ("queued", "running")
    assert result["job_id"] is not None
    row = conn.execute(
        "SELECT work_key FROM jobs WHERE id = ?", (result["job_id"],)
    ).fetchone()
    assert row is not None and row["work_key"]
    conn.close()
"""UR-004 / AC-004：本链路严格凭据解析与调用账本。

关键契约：

- user scope 只用本人配置，缺失/解密失败**不回退**系统配置；
- system scope 只用系统配置，不借用某个用户私钥；
- 任何解析结果只暴露 config_fingerprint，绝不暴露 Key；
- 配额预留与调用账本同事务提交，回滚一起回滚。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_credentials import (
    CallLedgerConflict,
    ResolvedCredential,
    UploadCredentialError,
    complete_llm_call,
    reserve_llm_call,
    resolve_upload_credentials,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-1', 101, 'k1', 'h1', 'private', 'interview', 'v1')"
    )
    conn.commit()
    return conn


def _user_cfg(api_key="user-secret-key"):
    return {
        "api_key": api_key,
        "base_url": "https://user.example.com/v1",
        "model": "user-model",
        "timeout": 60,
        "api_format": "openai",
    }


def _global_cfg():
    return {
        "api_key": "global-secret-key",
        "base_url": "https://system.example.com/v1",
        "model": "system-model",
        "timeout": 60,
        "api_format": "openai",
    }


class _Calls:
    def __init__(self):
        self.user_calls = []
        self.global_calls = 0

    def user_loader(self, user_id):
        self.user_calls.append(user_id)
        return _user_cfg()

    def global_loader(self):
        self.global_calls += 1
        return _global_cfg()


# ── 解析 ─────────────────────────────────────────────────────


def test_user_missing_key_needs_action_without_fallback():
    calls = _Calls()
    calls.user_loader = lambda user_id: None  # 本人未配置
    with pytest.raises(UploadCredentialError) as exc:
        resolve_upload_credentials(
            credential_scope="user",
            user_id=101,
            stage="extract",
            user_config_loader=calls.user_loader,
            global_config_loader=calls.global_loader,
        )
    assert exc.value.code == "MODEL_CONFIG_MISSING"
    assert exc.value.scope == "user"
    assert exc.value.action == "configure_user_model"
    assert exc.value.retryable is False
    assert calls.global_calls == 0, "不得静默回退系统配置"


def test_user_config_failure_never_borrows_system_key():
    def broken_loader(user_id):
        raise RuntimeError("decrypt failed: secret-material-123")

    calls = _Calls()
    with pytest.raises(UploadCredentialError) as exc:
        resolve_upload_credentials(
            credential_scope="user",
            user_id=101,
            stage="extract",
            user_config_loader=broken_loader,
            global_config_loader=calls.global_loader,
        )
    assert exc.value.code == "MODEL_CONFIG_MISSING"
    assert exc.value.scope == "user"
    assert calls.global_calls == 0
    assert "secret-material-123" not in str(exc.value), "错误信息不得泄露配置内容"


def test_system_scope_never_borrows_user_key():
    calls = _Calls()
    calls.global_loader = lambda: None  # 系统未配置
    with pytest.raises(UploadCredentialError) as exc:
        resolve_upload_credentials(
            credential_scope="global",
            user_id=101,
            stage="extract",
            user_config_loader=calls.user_loader,
            global_config_loader=calls.global_loader,
        )
    assert exc.value.scope == "global"
    assert exc.value.action == "configure_system_model"
    assert calls.user_calls == [], "system scope 不得读取用户配置"


def test_invalid_scope_is_rejected():
    with pytest.raises(ValueError):
        resolve_upload_credentials(
            credential_scope="root",
            user_id=101,
            stage="extract",
            user_config_loader=lambda u: _user_cfg(),
            global_config_loader=_global_cfg,
        )


def test_resolved_credential_exposes_fingerprint_not_key():
    resolved = resolve_upload_credentials(
        credential_scope="user",
        user_id=101,
        stage="extract",
        user_config_loader=lambda u: _user_cfg(),
        global_config_loader=_global_cfg,
    )
    assert isinstance(resolved, ResolvedCredential)
    assert resolved.scope == "user"
    assert resolved.payer_type == "user"
    assert resolved.payer_user_id == 101
    assert resolved.model == "user-model"
    dumped = repr(resolved) + str(resolved.model_dump())
    assert "user-secret-key" not in dumped
    assert resolved.config_fingerprint


def test_system_scope_resolves_system_payer():
    resolved = resolve_upload_credentials(
        credential_scope="global",
        user_id=101,
        stage="extract",
        user_config_loader=lambda u: _user_cfg(),
        global_config_loader=_global_cfg,
    )
    assert resolved.scope == "global"
    assert resolved.payer_type == "system"
    assert resolved.payer_user_id is None
    assert resolved.model == "system-model"


# ── 调用账本与配额 ────────────────────────────────────────────


def _reserve(conn, **overrides):
    payload = {
        "root_import_id": "imp-1",
        "stage": "extract",
        "unit_key": "document",
        "call_key": "imp-1:extract:document:1",
        "credential_scope": "user",
        "payer_type": "user",
        "payer_user_id": 101,
        "provider": "openai",
        "model": "user-model",
        "config_fingerprint": "fp",
    }
    payload.update(overrides)
    return reserve_llm_call(conn, **payload)


def test_reserve_call_records_scope_and_payer():
    conn = _db()
    _reserve(conn)
    row = conn.execute("SELECT * FROM upload_llm_calls").fetchone()
    assert row["credential_scope"] == "user"
    assert row["payer_type"] == "user"
    assert row["payer_user_id"] == 101
    assert row["status"] == "reserved"
    assert row["config_fingerprint"] == "fp"
    conn.close()


def test_reserve_call_is_atomic_with_user_quota():
    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    _reserve(conn)
    assert conn.execute("SELECT COUNT(*) FROM upload_llm_calls").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 1
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM upload_llm_calls").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 0
    conn.close()


def test_quota_exceeded_blocks_new_call_and_writes_no_ledger_row():
    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    _reserve(conn, call_key="first")
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    with pytest.raises(UploadCredentialError) as exc:
        _reserve(conn, call_key="second", daily_limit=1)
    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.retryable is False
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM upload_llm_calls").fetchone()[0] == 1
    conn.close()


def test_duplicate_call_key_is_rejected():
    conn = _db()
    _reserve(conn)
    with pytest.raises(CallLedgerConflict):
        _reserve(conn)
    conn.close()


def test_complete_llm_call_can_record_unknown_for_lost_response():
    conn = _db()
    _reserve(conn)
    complete_llm_call(
        conn, call_key="imp-1:extract:document:1", status="unknown", error_code="UPSTREAM_TIMEOUT"
    )
    row = conn.execute("SELECT * FROM upload_llm_calls").fetchone()
    assert row["status"] == "unknown"
    assert row["error_code"] == "UPSTREAM_TIMEOUT"
    assert row["finished_at"] is not None
    conn.close()


def test_system_payer_call_is_not_charged_to_user_quota():
    conn = _db()
    _reserve(
        conn,
        credential_scope="global",
        payer_type="system",
        payer_user_id=None,
        call_key="sys-1",
    )
    assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 0
    conn.close()


def test_user_scope_never_borrows_system_stub():
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

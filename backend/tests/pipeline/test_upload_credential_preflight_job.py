"""R01/AC-004：真实模型可用性预检。

覆盖：
- accept 创建首个模型 job 后，同事务写入 credential_preflight job；
- worker 预检任务用解析出的凭据做真实探测（provider ping）：
  成功 → 标记 preflight succeeded，提取 job 可派发；
  401/配置缺失 → MODEL_AUTH_INVALID/MODEL_CONFIG_MISSING，根任务
  needs_action，**不派发提取**；
  provider 404/超时 → UPSTREAM_UNAVAILABLE 阻塞不伪造成功；
- 预检的 scope 由 policy 决定：shared 普通用户先验 user，管理员 public
  先验 global；用户 scope 绝不借用 global 凭据探测。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_lifecycle import accept_upload


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (101, 'u101', 'x', 0)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) VALUES (201, 'u201', 'x', 1)"
    )
    conn.commit()
    return conn


def _accept(conn, *, key="k-1", target="private", is_admin=False, extra=None):
    params = {
        "actor_id": 201 if is_admin else 101,
        "actor_is_admin": is_admin,
        "idempotency_key": key,
        "target_intent": target,
        "text": "面经：解释 TCP 三次握手",
        "position_id": 1,
        "position_name": "后端开发",
        "job_position": "后端开发",
        "credential_loaders": {
            "user": lambda uid: {
                "api_key": "user-key",
                "base_url": "https://user.example.com/v1",
                "model": "user-model",
            },
            "global": lambda: {
                "api_key": "global-key",
                "base_url": "https://global.example.com/v1",
                "model": "global-model",
            },
        },
    }
    if extra:
        params.update(extra)
    return accept_upload(conn, **params)


def test_accept_creates_preflight_job_for_new_private_upload():
    """R01：接受新上传时同事务创建 preflight job（user scope, 服务端 policy）。"""

    conn = _db()
    result = _accept(conn)
    conn.commit()
    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (result["import_id"],),
    ).fetchone()
    assert preflight is not None, "新上传必须创建 credential_preflight job"
    payload_row = conn.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (preflight["id"],)
    ).fetchone()
    payload = json.loads(payload_row["payload"])
    assert payload["credential_scope"] == "user", "普通用户 private 预检 user scope"
    assert payload["user_id"] == 101
    assert payload["root_import_id"] == result["import_id"]
    conn.close()


def test_accept_shared_admin_preflights_global_scope():
    """R01：管理员 share（显式公共导入）预检 global scope。"""

    conn = _db()
    result = _accept(conn, key="k-share", target="share", is_admin=True)
    conn.commit()
    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (result["import_id"],),
    ).fetchone()
    payload = json.loads(
        conn.execute(
            "SELECT payload FROM job_payloads WHERE job_id = ?", (preflight["id"],)
        ).fetchone()["payload"]
    )
    assert payload["credential_scope"] == "global", "管理员 share 预检 global"
    conn.close()


def test_accept_shared_regular_user_preflights_both_scopes_before_business_work():
    """普通用户公共申请先验公共与个人模型；任一未通过都不能建提取 job。"""

    conn = _db()
    result = _accept(conn, key="k-share-u", target="share", is_admin=False)
    conn.commit()
    preflights = conn.execute(
        "SELECT j.id, j.upload_attempt_id, p.payload FROM jobs j "
        "JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' ORDER BY j.id",
        (result["import_id"],),
    ).fetchall()
    scopes = {json.loads(row["payload"])["credential_scope"] for row in preflights}
    assert scopes == {"user", "global"}
    assert len({row["upload_attempt_id"] for row in preflights}) == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (result["import_id"],),
    ).fetchone()[0] == 0
    conn.close()


def test_shared_upload_creates_submit_job_only_after_both_preflights_succeed():
    """scope 预检按 attempt 聚合，第二个 scope 通过后才创建提取 job。"""

    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    result = _accept(conn, key="k-share-gate", target="share")
    conn.commit()
    rows = conn.execute(
        "SELECT j.id, j.upload_attempt_id, p.payload FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight'",
        (result["import_id"],),
    ).fetchall()
    assert len(rows) == 2

    for row in rows:
        payload = json.loads(row["payload"])
        outcome = run_credential_preflight(
            conn,
            job_id=row["id"],
            probe=lambda credential: {"status": "ok", "latency_ms": 1},
            user_config_loader=lambda uid: {
                "api_key": "user-key",
                "base_url": "https://user.example.com/v1",
                "model": "user-model",
            },
            global_config_loader=lambda: {
                "api_key": "global-key",
                "base_url": "https://global.example.com/v1",
                "model": "global-model",
            },
        )
        assert outcome.status == "ok"
        successful_scopes = conn.execute(
            "SELECT COUNT(DISTINCT json_extract(p.payload, '$.credential_scope')) "
            "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
            "JOIN upload_stage_results s ON s.job_id = j.id "
            "AND s.stage = 'credential_preflight' "
            "AND s.status = 'succeeded' WHERE j.root_import_id = ?",
            (result["import_id"],),
        ).fetchone()[0]
        submit_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
            (result["import_id"],),
        ).fetchone()[0]
        assert submit_count == (1 if successful_scopes == 2 else 0)

    submits = conn.execute(
        "SELECT id, upload_attempt_id FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (result["import_id"],),
    ).fetchall()
    assert len(submits) == 1
    assert submits[0]["upload_attempt_id"] == rows[0]["upload_attempt_id"]
    conn.close()


def test_preflight_success_marks_stage_and_keeps_extract_dispatchable():
    """R01：探测成功 → preflight 阶段 succeeded，根任务保持 queued（可派发提取）。"""

    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    result = _accept(conn)
    conn.commit()
    import_id = result["import_id"]
    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()

    def _probe_ok(credential):
        assert credential.scope == "user", "探测使用 policy scope 的凭据"
        return {"status": "ok", "latency_ms": 42, "provider": "openai"}

    outcome = run_credential_preflight(
        conn,
        job_id=preflight["id"],
        probe=_probe_ok,
        user_config_loader=lambda uid: {
            "api_key": "user-key",
            "base_url": "https://user.example.com/v1",
            "model": "user-model",
        },
    )
    conn.commit()
    assert outcome.status == "ok"
    stage = conn.execute(
        "SELECT * FROM upload_stage_results WHERE import_id = ? "
        "AND stage = 'credential_preflight'",
        (import_id,),
    ).fetchone()
    assert stage is not None and stage["status"] == "succeeded"
    root = conn.execute(
        "SELECT status FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert root["status"] == "queued", "预检成功不阻塞提取派发"
    conn.close()


def test_preflight_auth_failure_blocks_extract_with_needs_action():
    """R01：探测 401 → MODEL_AUTH_INVALID，根 needs_action，不派发提取。"""

    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    result = _accept(conn)
    conn.commit()
    import_id = result["import_id"]
    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()

    def _probe_401(credential):
        raise RuntimeError("401: invalid api key")

    outcome = run_credential_preflight(
        conn,
        job_id=preflight["id"],
        probe=_probe_401,
        user_config_loader=lambda uid: {
            "api_key": "user-key",
            "base_url": "https://user.example.com/v1",
            "model": "user-model",
        },
    )
    conn.commit()
    assert outcome.status == "blocked"
    assert outcome.error_code == "MODEL_AUTH_INVALID"
    root = conn.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert root["status"] == "needs_action"
    assert root["error_code"] == "MODEL_AUTH_INVALID"
    # 未通过预检时没有任何业务提取 job
    extract = conn.execute(
        "SELECT status FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert extract is None
    conn.close()


def test_preflight_provider_down_uses_upstream_unavailable():
    """R01：provider 404/不可达 → UPSTREAM_UNAVAILABLE，阻塞不伪造成功。"""

    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    result = _accept(conn)
    conn.commit()
    import_id = result["import_id"]
    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()

    def _probe_down(credential):
        raise RuntimeError("404: model not found")

    outcome = run_credential_preflight(
        conn,
        job_id=preflight["id"],
        probe=_probe_down,
        user_config_loader=lambda uid: {
            "api_key": "user-key",
            "base_url": "https://user.example.com/v1",
            "model": "user-model",
        },
    )
    conn.commit()
    assert outcome.status == "blocked"
    assert outcome.error_code == "UPSTREAM_UNAVAILABLE"
    stage = conn.execute(
        "SELECT status, error_code FROM upload_stage_results "
        "WHERE import_id = ? AND stage = 'credential_preflight'",
        (import_id,),
    ).fetchone()
    assert stage["status"] == "failed"
    assert stage["error_code"] == "UPSTREAM_UNAVAILABLE"
    conn.close()

def test_preflight_success_clears_needs_action_after_config_fix():
    """R01：配置修复后再次预检成功 → root 从 needs_action 回 queued（同 root 继续）。"""

    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    result = _accept(conn)
    conn.commit()
    import_id = result["import_id"]
    # 首次预检失败 → needs_action
    conn.execute(
        "UPDATE upload_imports SET status = 'needs_action', error_code = 'MODEL_AUTH_INVALID', "
        "error_message = 'bad key' WHERE id = ?",
        (import_id,),
    )
    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()
    conn.execute(
        "UPDATE jobs SET status = 'failed', completed_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (preflight["id"],),
    )
    # 同时释放 attempt 1 的 active 占用，让恢复可开新批次（模拟工作全部终态失败）
    conn.execute(
        "UPDATE upload_attempts SET status = 'failed', completed_at = CURRENT_TIMESTAMP "
        "WHERE import_id = ? AND status = 'active'",
        (import_id,),
    )
    conn.commit()

    # 配置修复后恢复 → 建立新的预检 job → 探测成功后原子创建提取 job
    from app.services.upload_lifecycle import restore_upload

    restored = restore_upload(conn, actor_id=101, import_id=import_id)
    conn.commit()
    new_preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight' "
        "AND status IN ('pending','queued','running')",
        (import_id,),
    ).fetchone()
    assert new_preflight is not None, "恢复必须重新建立预检 job"

    def _probe_ok(credential):
        return {"status": "ok", "latency_ms": 30, "provider": "openai"}

    outcome = run_credential_preflight(
        conn,
        job_id=new_preflight["id"],
        probe=_probe_ok,
        user_config_loader=lambda uid: {
            "api_key": "user-key",
            "base_url": "https://user.example.com/v1",
            "model": "user-model",
        },
    )
    conn.commit()
    assert outcome.status == "ok"
    root = conn.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert root["status"] == "queued", "预检通过后根任务应回到 queued 可派发"
    assert root["error_code"] is None
    assert restored["planned_job_id"], "恢复先规划 durable preflight job"
    extract = conn.execute(
        "SELECT status FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert extract is not None and extract["status"] == "pending"
    conn.close()


def test_preflight_success_writes_llm_accounting_with_fingerprint():
    """AC-004：预检成功必须写 upload_llm_calls 账本（provider/model/
    config_fingerprint 绑定），并在阶段结果里保留指纹；不存 Key。"""

    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    result = _accept(conn)
    conn.commit()
    root_import_id = result["import_id"]
    preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (root_import_id,),
    ).fetchone()
    preflight_job_id = int(preflight["id"])

    captured = {}

    def _probe(credential):
        captured["fingerprint"] = getattr(credential, "config_fingerprint", None)
        captured["provider"] = getattr(credential, "provider", None)
        captured["model"] = getattr(credential, "model", None)
        return {
            "status": "ok",
            "latency_ms": 128,
            "provider": captured["provider"] or "openai",
        }

    outcome = run_credential_preflight(
        conn,
        job_id=preflight_job_id,
        probe=_probe,
        user_config_loader=lambda uid: {
            "api_key": "user-key",
            "base_url": "https://user.example.com/v1",
            "model": "user-model",
        },
    )
    assert outcome.status == "ok"

    # 账本：reserved 次数=1（预检一次物理调用），绑定 provider/model/fingerprint
    calls = conn.execute(
        "SELECT * FROM upload_llm_calls WHERE root_import_id = ?",
        (root_import_id,),
    ).fetchall()
    assert len(calls) == 1, "预检必须登记一次独立调用记账"
    call = calls[0]
    assert call["stage"] == "credential_preflight"
    assert call["status"] in ("reserved", "succeeded")
    assert call["provider"]
    assert call["model"]
    assert call["config_fingerprint"], "账本必须绑定配置指纹"

    # 阶段结果保留指纹（不发 Key/认证头）
    stage = conn.execute(
        "SELECT result_json FROM upload_stage_results "
        "WHERE import_id = ? AND stage = 'credential_preflight'",
        (root_import_id,),
    ).fetchone()
    stored = json.loads(stage["result_json"])
    assert stored.get("config_fingerprint"), "阶段结果必须保留配置指纹"
    assert "api_key" not in stored and "apiKey" not in stored
    conn.close()


def test_preflight_blocked_writes_failed_accounting_ledger():
    """AC-004：预检失败也记账（status=failed + error_code），阶段结果不伪造成功。"""

    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    result = _accept(conn)
    conn.commit()
    preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (result["import_id"],),
    ).fetchone()
    preflight_job_id = int(preflight["id"])

    def _probe(credential):
        raise PermissionError("401 Invalid API key")

    outcome = run_credential_preflight(
        conn,
        job_id=preflight_job_id,
        probe=_probe,
        user_config_loader=lambda uid: {
            "api_key": "user-key",
            "base_url": "https://user.example.com/v1",
            "model": "user-model",
        },
    )
    assert outcome.status == "blocked"
    assert outcome.error_code == "MODEL_AUTH_INVALID"

    calls = conn.execute(
        "SELECT status, error_code FROM upload_llm_calls "
        "WHERE stage = 'credential_preflight'"
    ).fetchall()
    assert len(calls) == 1, "失败的预检也必须记账（物理调用确实发生了）"
    assert calls[0]["status"] == "failed"
    assert calls[0]["error_code"] == "MODEL_AUTH_INVALID"
    conn.close()

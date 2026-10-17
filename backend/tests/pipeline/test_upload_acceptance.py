"""阶段C：接受上传（AC-003/004/021/022）。

契约（contracts.md §2.1、§4.1）：

- 同用户同幂等键同 hash 返回同一根任务；不同 hash 409；跨用户同键互不干扰。
- 文件校验先看 size：超限 413、非图片 400、空提交 400、超数量 400，且**不产生幽灵 job**。
- 原稿 + 根任务 + attempt + 首个 job 同事务；任一步失败全部回滚。
- 服务端计算 policy 与 request_hash；客户端传 is_admin/owner_id 等策略字段必须被拒绝。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_lifecycle import (
    UploadFileMeta,
    UploadInputError,
    accept_upload,
    compute_request_hash,
)
from app.services.upload_policy import ClientPolicyFieldError, InvalidTargetError


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO job_positions(id,name) VALUES(1, '后端')")
    for uid in (101, 102, 201):
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    conn.commit()
    return conn


def _accept(conn, **overrides):
    params = dict(
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="key-1",
        target_intent="private",
        source_type="interview",
        text="面经：解释 TCP 三次握手",
        url="",
        season="2026春招",
        content_type="",
        position_id=1,
        position_name="后端",
        files=[],
        images=[],
        entry="api",
        credential_loaders={
            "user": lambda uid: {
                "api_key": "user-key",
                "base_url": "https://user.example.com/v1",
                "model": "user-model",
                "timeout": 60,
            },
            "global": lambda: {
                "api_key": "global-key",
                "base_url": "https://system.example.com/v1",
                "model": "system-model",
                "timeout": 60,
            },
        },
    )
    params.update(overrides)
    return accept_upload(conn, **params)


def _jobs(conn):
    return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()


# ── 幂等与事务 ───────────────────────────────────────────────


def test_accept_creates_root_attempt_and_preflight_in_one_transaction():
    conn = _db()
    result = _accept(conn)
    assert result["created"] is True
    assert result["import_id"]
    assert result["status_url"].endswith(result["import_id"])
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    jobs = _jobs(conn)
    # AC-004：同事务持久化 attempt + preflight；provider ping 通过后再建业务 job。
    assert len(jobs) == 1, [dict(j) for j in jobs]
    submit_jobs = [j for j in jobs if j["job_type"] == "submit_import"]
    preflight_jobs = [j for j in jobs if j["job_type"] == "credential_preflight"]
    assert len(submit_jobs) == 0 and len(preflight_jobs) == 1
    assert preflight_jobs[0]["root_import_id"] == result["import_id"]
    assert result["job_id"] == preflight_jobs[0]["id"]
    conn.close()


def test_accept_rollback_removes_root_attempt_and_job():
    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    _accept(conn)
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_same_key_same_hash_returns_same_root_and_no_new_job():
    conn = _db()
    first = _accept(conn)
    second = _accept(conn)
    assert second["created"] is False
    assert second["import_id"] == first["import_id"]
    assert second["job_id"] == first["job_id"]
    # 同键复用不新建 job（只保留同 attempt 的 preflight）
    assert len(_jobs(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    conn.close()


def test_same_key_different_hash_conflicts():
    conn = _db()
    _accept(conn)
    with pytest.raises(Exception) as exc:
        _accept(conn, text="完全不同的另一篇面经")
    assert getattr(exc.value, "code", "") == "IDEMPOTENCY_CONFLICT"
    # 冲突后不产生幽灵 job：原 preflight 维持 1 条
    assert len(_jobs(conn)) == 1
    conn.close()


def test_same_key_isolated_between_users():
    conn = _db()
    mine = _accept(conn, actor_id=101)
    other = _accept(conn, actor_id=102)
    assert mine["import_id"] != other["import_id"]
    # 两人各 1 个 root → 每个 root 独立保留自己的 preflight。
    assert len(_jobs(conn)) == 2
    conn.close()


# ── policy 落库（四格） ──────────────────────────────────────


@pytest.mark.parametrize(
    "actor_id,actor_is_admin,target_intent,expect_scope,expect_payer",
    [
        (101, False, "private", "user", "user"),
        (101, False, "share", "user", "user"),
        (201, True, "private", "user", "user"),
        (201, True, "share", "global", "system"),
    ],
)
def test_accept_persists_server_policy(
    actor_id,
    actor_is_admin,
    target_intent,
    expect_scope,
    expect_payer,
):
    conn = _db()
    result = _accept(
        conn,
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
        target_intent=target_intent,
        idempotency_key=f"key-{actor_id}-{target_intent}",
    )
    row = conn.execute("SELECT * FROM upload_imports").fetchone()
    import json

    policy = json.loads(row["policy_json"])
    assert policy["credential_scope"] == expect_scope
    assert policy["payer"]["type"] == expect_payer
    assert result["status"] in ("queued", "needs_action")
    conn.close()


def test_accept_rejects_client_supplied_policy_fields():
    conn = _db()
    with pytest.raises(ClientPolicyFieldError):
        _accept(conn, policy_overrides={"is_admin": 1})
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize("bad_target", ["public", "invalid", ""])
def test_invalid_target_rejected_without_creating_job(bad_target):
    conn = _db()
    with pytest.raises((InvalidTargetError, UploadInputError)):
        _accept(conn, target_intent=bad_target)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


# ── 文件与输入校验（AC-022） ─────────────────────────────────


def test_non_image_file_rejected_without_ghost_job():
    conn = _db()
    with pytest.raises(UploadInputError) as exc:
        _accept(
            conn,
            files=[UploadFileMeta("resume.pdf", "application/pdf", 1024)],
        )
    assert exc.value.status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_oversize_file_rejected_before_read_without_ghost_job():
    conn = _db()
    with pytest.raises(UploadInputError) as exc:
        _accept(
            conn,
            files=[UploadFileMeta("big.png", "image/png", 11 * 1024 * 1024)],
        )
    assert exc.value.status_code == 413
    assert exc.value.code == "FILE_TOO_LARGE"
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_total_size_limit_enforced():
    conn = _db()
    files = [UploadFileMeta(f"img{i}.png", "image/png", 9 * 1024 * 1024) for i in range(6)]
    with pytest.raises(UploadInputError) as exc:
        _accept(conn, files=files)
    assert exc.value.status_code == 413
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_empty_submission_rejected():
    conn = _db()
    with pytest.raises(UploadInputError) as exc:
        _accept(conn, text="", files=[])
    assert exc.value.status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_too_many_files_rejected():
    conn = _db()
    files = [UploadFileMeta(f"i{n}.png", "image/png", 10) for n in range(21)]
    with pytest.raises(UploadInputError) as exc:
        _accept(conn, files=files)
    assert exc.value.status_code == 400
    conn.close()


def test_request_hash_changes_with_content_and_is_stable():
    a = compute_request_hash(
        text="A",
        url="",
        season="",
        target_intent="private",
        position_id=1,
        files=[],
    )
    b = compute_request_hash(
        text="A",
        url="",
        season="",
        target_intent="private",
        position_id=1,
        files=[],
    )
    c = compute_request_hash(
        text="B",
        url="",
        season="",
        target_intent="private",
        position_id=1,
        files=[],
    )
    assert a == b
    assert a != c


# ── 凭据阻塞（AC-004） ────────────────────────────────────────


def test_missing_user_key_accepts_root_as_needs_action_without_llm_calls():
    """U1 无 Key、系统 Key 有效：原稿被接受，root=needs_action，0 次外部调用。"""

    conn = _db()
    calls = {"user": 0, "global": 0}

    def user_loader(user_id):
        calls["user"] += 1
        return None

    def global_loader():
        calls["global"] += 1
        return {
            "api_key": "global-key",
            "base_url": "https://system.example.com/v1",
            "model": "system-model",
            "timeout": 60,
        }

    result = _accept(
        conn,
        credential_loaders={"user": user_loader, "global": global_loader},
    )
    assert result["status"] == "needs_action"
    assert result["error"]["code"] == "MODEL_CONFIG_MISSING"
    assert result["job_id"] is not None, "无 Key 时也必须保存可恢复的 preflight job"
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_type = 'submit_import'"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM upload_llm_calls").fetchone()[0] == 0
    assert calls["global"] == 0, "个人上传绝不借用系统配置"

    # 原稿、根任务、attempt 和预检 outbox 都在，尚无业务 job
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1


def test_fixing_config_allows_restore_of_same_root():
    conn = _db()
    result = _accept(
        conn,
        credential_loaders={"user": lambda uid: None, "global": lambda: None},
    )
    assert result["status"] == "needs_action"

    from app.services.credential_preflight import run_credential_preflight

    preflight = conn.execute(
        "SELECT id FROM jobs WHERE job_type = 'credential_preflight'"
    ).fetchone()
    blocked = run_credential_preflight(
        conn,
        job_id=preflight["id"],
        user_config_loader=lambda uid: None,
        global_config_loader=lambda: None,
    )
    assert blocked.status == "blocked"

    from app.services.upload_lifecycle import restore_upload

    restored = restore_upload(conn, actor_id=101, import_id=result["import_id"])
    assert restored["import_id"] == result["import_id"]
    assert restored["created_attempt"] is True


def test_accept_resolves_type_from_content_hint():
    """contracts §1.1：content_type_hint=auto 时按内容识别并记录
    resolved_type（jd/interview）；明确 hint 直接采用。"""

    conn = _db()
    # auto + JD 文本 → resolved_type=jd
    result = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="k-jd-auto",
        target_intent="private",
        source_type="auto",
        content_type="auto",
        text="岗位JD：后端开发工程师，负责API设计与数据库性能优化，要求3年经验",
        position_id=1,
        position_name="后端",
        job_position="后端",
        credential_loaders={
            "user": lambda uid: {
                "api_key": "k",
                "base_url": "https://u.example.com/v1",
                "model": "m",
            }
        },
    )
    conn.commit()
    row = conn.execute(
        "SELECT resolved_type FROM upload_imports WHERE id = ?",
        (result["import_id"],),
    ).fetchone()
    assert row["resolved_type"] == "jd", "auto 识别 JD 文本必须记录 resolved_type=jd"

    # 明确 interview hint → resolved_type=interview
    result2 = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="k-iv-hint",
        target_intent="private",
        source_type="interview",
        content_type="interview",
        text="面经：TCP 三次握手",
        position_id=1,
        position_name="后端",
        job_position="后端",
        credential_loaders={
            "user": lambda uid: {
                "api_key": "k",
                "base_url": "https://u.example.com/v1",
                "model": "m",
            }
        },
    )
    conn.commit()
    row2 = conn.execute(
        "SELECT resolved_type FROM upload_imports WHERE id = ?",
        (result2["import_id"],),
    ).fetchone()
    assert row2["resolved_type"] == "interview"
    conn.close()


def test_admin_public_import_persists_audit_trail():
    """README §3：管理员显式公共导入「视为记录了审批的公共处理」——
    root 必须持久化可查询的审计痕迹（audit_public_import + requester +
    entry + target_intent），而不是仅存在于内存判断。"""

    import json as _json

    conn = _db()
    result = _accept(
        conn,
        actor_id=201,
        actor_is_admin=True,
        target_intent="share",
        idempotency_key="admin-public-1",
        entry="api",
    )
    conn.commit()

    root = conn.execute(
        "SELECT * FROM upload_imports WHERE id = ?", (result["import_id"],)
    ).fetchone()
    policy = _json.loads(root["policy_json"])
    assert policy["audit_public_import"] is True, (
        "管理员公共导入必须留下 audit_public_import 审计标记"
    )
    assert policy["write_scope"] == "public"
    assert root["requester_id"] == 201, "审计必须记录发起管理员"
    assert root["target_intent"] == "share"
    assert root["idempotency_key"] == "admin-public-1"
    # 审计痕迹可通过 admin 运维白名单查询（scope/状态/发起者）
    ops = conn.execute(
        "SELECT json_extract(policy_json, '$.audit_public_import') AS audit, "
        "requester_id FROM upload_imports WHERE id = ?",
        (result["import_id"],),
    ).fetchone()
    assert int(ops["audit"]) == 1
    conn.close()

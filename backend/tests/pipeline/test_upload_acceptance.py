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
    )
    params.update(overrides)
    return accept_upload(conn, **params)


def _jobs(conn):
    return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()


# ── 幂等与事务 ───────────────────────────────────────────────


def test_accept_creates_root_attempt_and_job_in_one_transaction():
    conn = _db()
    result = _accept(conn)
    assert result["created"] is True
    assert result["import_id"]
    assert result["status_url"].endswith(result["import_id"])
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    jobs = _jobs(conn)
    assert len(jobs) == 1
    assert jobs[0]["root_import_id"] == result["import_id"]
    assert jobs[0]["work_key"]
    assert result["job_id"] == jobs[0]["id"]
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
    assert len(_jobs(conn)) == 1
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    conn.close()


def test_same_key_different_hash_conflicts():
    conn = _db()
    _accept(conn)
    with pytest.raises(Exception) as exc:
        _accept(conn, text="完全不同的另一篇面经")
    assert getattr(exc.value, "code", "") == "IDEMPOTENCY_CONFLICT"
    assert len(_jobs(conn)) == 1
    conn.close()


def test_same_key_isolated_between_users():
    conn = _db()
    mine = _accept(conn, actor_id=101)
    other = _accept(conn, actor_id=102)
    assert mine["import_id"] != other["import_id"]
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

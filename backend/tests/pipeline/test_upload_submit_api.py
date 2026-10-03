"""接受入口 API（AC-003/021/022 的接口面）。

- `POST /api/submit-jobs`（唯一上传写入口）返回稳定 import_id/status_url/幂等键；
  同键同 hash 复用，不同 hash 409。（v2 已收口为唯一路径）
- 非法 target 400、超限 413，且不产生幽灵 job。
- `GET /api/upload-imports/by-key/{key}` 只能查到本人的任务。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def _no_dispatch():
    with patch("app.worker_enqueue.enqueue_submit_import_job", new=AsyncMock()) as submit_enq:
        with patch(
            "app.worker_enqueue.enqueue_credential_preflight_job", new=AsyncMock()
        ) as preflight_enq:
            yield {"submit": submit_enq, "preflight": preflight_enq}


def _login(client, user):
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _v2_on(monkeypatch):
    """上传恢复 v2 已全量收口（无灰度 flag）：保留空实现，标记这些用例
    覆盖统一接受服务行为（2026-10-01 收口，flag 已删除）。"""
    return None


def _seed_user_models(test_db, uids=(101, 201)):
    """为测试用户配置个人模型：strict user-only 读取下私人 scope 预检才通过。

    AC-004 修复后上传链路私人阶段走 ``get_strict_user_llm_config``，本人缺
    配置时即使 global 有效也置 needs_action。需要成功建 job 的用例必须先
    为用户写入 ``user_llm_config``（明文即可，decrypt 对明文容错）。
    """

    for uid in uids:
        test_db.execute(
            "INSERT OR IGNORE INTO user_llm_config (user_id, api_key, base_url, model) "
            "VALUES (?, 'user-key', 'https://user.example.com/v1', 'user-model')",
            (uid,),
        )
    test_db.commit()


def _post(
    client,
    *,
    text="面经：解释 TCP 三次握手",
    target="private",
    key="k-1",
    url="",
    files=None,
):
    data = {"text": text, "target": target, "url": url, "season": "2026春招"}
    if files:
        data["url"] = ""
    return client.post(
        "/api/submit-jobs",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Idempotency-Key": key,
        },
        data=data,
        files=files,
    )


@pytest.mark.parametrize(
    "entry_user,is_admin,target",
    [
        ({"id": 101, "is_admin": 0, "username": "u101"}, 0, "private"),
        ({"id": 101, "is_admin": 0, "username": "u101"}, 0, "share"),
        ({"id": 201, "is_admin": 1, "username": "u201"}, 1, "private"),
        ({"id": 201, "is_admin": 1, "username": "u201"}, 1, "share"),
    ],
)
def test_submit_jobs_v2_returns_stable_import_id(
    client, monkeypatch, _no_dispatch, entry_user, is_admin, target, test_db
):
    for uid in (101, 201):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    _seed_user_models(test_db)
    _v2_on(monkeypatch)
    for login in _login(client, entry_user):
        resp = _post(client, target=target, key=f"k-{is_admin}-{target}")
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["import_id"]
        assert body["status_url"].endswith(body["import_id"])
        assert body["job_id"]
        assert body["idempotency_key"] == f"k-{is_admin}-{target}"
        # 同键重发：复用同一根任务
        again = _post(client, target=target, key=f"k-{is_admin}-{target}")
        assert again.status_code == 202
        assert again.json()["import_id"] == body["import_id"]
        assert again.json()["created"] is False


def test_submit_jobs_v2_conflict_on_same_key_different_content(
    client, monkeypatch, _no_dispatch, test_db
):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    _seed_user_models(test_db, uids=(101,))
    _v2_on(monkeypatch)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        first = _post(client, text="第一篇面经", key="same")
        assert first.status_code == 202
        conflict = _post(client, text="完全不同的第二篇面经", key="same")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]


def test_upload_import_stream_emits_only_the_snapshot_contract(
    client, monkeypatch, _no_dispatch, test_db
):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    _seed_user_models(test_db, uids=(101,))
    _v2_on(monkeypatch)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        accepted = _post(client, key="stream-snapshot")
        assert accepted.status_code == 202, accepted.text
        import_id = accepted.json()["import_id"]
        test_db.execute(
            "UPDATE upload_imports SET status = 'completed' WHERE id = ?",
            (import_id,),
        )
        test_db.commit()

        response = client.get(f"/api/upload-imports/{import_id}/stream")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    event = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
    snapshot = json.loads(event)
    assert snapshot["import_id"] == import_id
    assert snapshot["status"] == "completed"


def test_by_key_returns_only_own_import(client, monkeypatch, _no_dispatch, test_db):
    for uid in (101, 102):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    _seed_user_models(test_db, uids=(101,))
    _v2_on(monkeypatch)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        created = _post(client, key="mine-only").json()
    for _ in _login(client, {"id": 102, "is_admin": 0, "username": "u102"}):
        assert client.get("/api/upload-imports/by-key/mine-only").status_code == 404
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        found = client.get("/api/upload-imports/by-key/mine-only")
        assert found.status_code == 200
        assert found.json()["import_id"] == created["import_id"]


def test_invalid_target_returns_400_without_ghost_job(client, monkeypatch, _no_dispatch, test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    test_db.commit()
    _v2_on(monkeypatch)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = _post(client, target="public")
        assert resp.status_code == 400
    jobs = test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert jobs == 0
    assert test_db.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0


def test_oversize_file_returns_413_without_ghost_job(client, monkeypatch, _no_dispatch, test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    test_db.commit()
    _v2_on(monkeypatch)
    monkeypatch.setattr("app.services.upload_lifecycle.MAX_FILE_SIZE", 64)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post(
            "/api/submit-jobs",
            headers={"Idempotency-Key": "big-file", "X-Requested-With": "XMLHttpRequest"},
            data={"text": "x", "target": "private"},
            files=[("files", ("big.png", b"\x89PNG" + b"0" * 200, "image/png"))],
        )
        assert resp.status_code == 413
    assert test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_legacy_sse_entry_rejects_invalid_target(client, monkeypatch, test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    test_db.commit()
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post(
            "/api/submit-stream-v2",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={"text": "面经正文", "target": "public"},
        )
        assert resp.status_code == 400
    assert test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_legacy_sse_entry_uses_accept_service_not_inline_graph(
    client, monkeypatch, _no_dispatch, test_db
):
    """AC-003 + contracts §8：旧 SSE 只创建根任务并订阅快照，绝不自己启动 graph。

    灰度收口（2026-10-01）后 submit 路由不存在可写 graph 入口：
    全系统仅 worker 一条写路径。
    """

    import inspect

    import app.routers.submit as submit_module

    # 结构性断言：路由层不得保留第二套可写图执行入口
    assert not hasattr(submit_module, "stream_submit_graph"), (
        "旧 SSE 入口不得保留可写 graph；上传执行只能由 worker 进行"
    )
    assert "stream_submit_graph" not in inspect.getsource(submit_module), (
        "submit 路由不得引用可写 graph（contracts §8）"
    )

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    _seed_user_models(test_db, uids=(101,))
    monkeypatch.setattr(submit_module, "LEGACY_SSE_MAX_POLLS", 1)

    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        headers = {"Idempotency-Key": "sse-1", "X-Requested-With": "XMLHttpRequest"}
        payload = {"text": "面经：解释 TCP 三次握手", "target": "private"}
        resp = client.post(
            "/api/submit-stream-v2",
            headers=headers,
            data=payload,
        )
        assert resp.status_code == 200
        assert "event: snapshot" in resp.text
        event_data = json.loads(resp.text.split("data: ", 1)[1].splitlines()[0])
        first_import_id = event_data["import_id"]
        assert event_data["progress"] == {
            "unit": "questions",
            "completed": 0,
            "total": None,
        }
        assert event_data["counts"]["total"] is None

        job_ids_before = [
            row["id"]
            for row in test_db.execute(
                "SELECT id FROM jobs WHERE root_import_id = ? ORDER BY id",
                (first_import_id,),
            ).fetchall()
        ]
        again = client.post("/api/submit-stream-v2", headers=headers, data=payload)
        assert again.status_code == 200
        second_event = json.loads(again.text.split("data: ", 1)[1].splitlines()[0])
        assert second_event["import_id"] == first_import_id
        assert [
            row["id"]
            for row in test_db.execute(
                "SELECT id FROM jobs WHERE root_import_id = ? ORDER BY id",
                (first_import_id,),
            ).fetchall()
        ] == job_ids_before

    row = test_db.execute("SELECT * FROM upload_imports").fetchone()
    assert row is not None, "旧入口必须落根任务"
    assert row["id"] == first_import_id
    assert test_db.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 1


def test_submit_jobs_default_config_uses_unified_accept_service(
    client, _no_dispatch, test_db
):
    """critical 错配回归：默认配置（不设任何开关/不 monkeypatch）下，
    `/api/submit-jobs` 必须走统一接受服务并落 `upload_imports` 根任务。

    历史缺陷：旧 flag 默认 off 时该入口创建裸 job，不写 upload_imports，
    前端任务中心读不到任何任务（前后端错配）。
    """

    for uid in (101,):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    _seed_user_models(test_db, uids=(101,))

    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = _post(client, target="private", key="default-cfg-1")
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["import_id"], "默认配置必须返回稳定 import_id"

    root = test_db.execute("SELECT * FROM upload_imports").fetchone()
    assert root is not None, (
        "默认配置下 /api/submit-jobs 必须写 upload_imports（前端任务中心数据源）"
    )
    assert root["id"] == "default-cfg-1" or root["idempotency_key"] == "default-cfg-1"
    # 预检 outbox 与根任务同事务；真实 provider 探测通过后才建 submit job。
    preflight = test_db.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (root["id"],),
    ).fetchone()
    assert preflight is not None, "接受事务必须持久化模型预检任务"
    assert test_db.execute(
        "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (root["id"],),
    ).fetchone()[0] == 0


def test_share_duplicate_check_ignores_personal_source_urls(
    client, _no_dispatch, test_db
):
    """公共重复检查只看公共源；另一用户的个人 URL 不应阻塞公共申请。"""

    for uid in (101, 102):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    _seed_user_models(test_db, uids=(101,))
    url = "https://example.com/jobs/private-source-1"
    test_db.execute(
        "INSERT INTO interview (url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (?, 'private', '一面', '1.题目', 102, 'approved', '后端')",
        (url,),
    )
    test_db.commit()

    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        response = _post(client, target="share", key="scope-share", url=url)

    assert response.status_code == 202, response.text


def test_share_duplicate_check_still_rejects_public_source_urls(
    client, _no_dispatch, test_db
):
    for uid in (101,):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    _seed_user_models(test_db, uids=(101,))
    url = "https://example.com/jobs/public-source-1"
    test_db.execute(
        "INSERT INTO interview (url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (?, 'public', '一面', '1.题目', NULL, 'approved', '后端')",
        (url,),
    )
    test_db.commit()

    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        response = _post(client, target="share", key="same-scope-share", url=url)

    assert response.status_code == 409

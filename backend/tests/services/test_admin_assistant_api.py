"""管理员 AI 助手 API 测试：对话 / 确认执行 / 历史 / 审计。

写操作（approve/reject/batch）必须走「内联确认门」：LLM 提议 → 暂存 → 管理员确认。
本测试 mock `app.services.admin_assistant_service.llm_with_tools`（AsyncMock side_effect
脚本化响应序列），验证工具循环、写门、确认端点、审计落库与续接回执。
"""
import json

import pytest
from unittest.mock import AsyncMock


# ── 种子数据（quality_issue 表由迁移 068 建立，admin_assistant_log 由迁移 069） ──


def _seed_quality_issue_db(conn):
    conn.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(1, '介绍RAG流程', 4, 'approved', 'B2.RAG系统设计', ?)",
        (
            json.dumps(
                ["介绍rag流程", "RAG是怎么做的", "关于研究生方向", "RAG各个部分怎么做"],
                ensure_ascii=False,
            ),
        ),
    )
    conn.execute(
        "INSERT INTO quality_issue (qb_id, variant_index, issue_type, suggested_action, "
        "reason, suggested_value, confidence, status, created_at) VALUES "
        "(1, 2, 'mismerge', 'split', '考察点不同', NULL, 0.9, 'pending', 'now'),"
        "(1, 1, 'mismerge', 'dedupe', '重复', NULL, 0.9, 'pending', 'now'),"
        "(1, 0, 'weak_representative', 'refine_representative', '代表题过弱', '更好的题面', 0.6, 'pending', 'now')"
    )
    conn.commit()


def _admin_headers(user_id=1, is_admin=True):
    from app.core.auth import create_access_token

    token = create_access_token({"user_id": user_id, "type": "access", "is_admin": is_admin})
    return {"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"}


def _ensure_admin_user(test_db, user_id=1):
    test_db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
    test_db.commit()


def _ensure_normal_user(test_db, user_id=9):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (?, 'normal_user', 'TEST_HASH_PLACEHOLDER', 0)",
        (user_id,),
    )
    test_db.commit()


def _tool_call(name, arguments: dict, call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _final_response(text="好的。"):
    return {"content": text, "tool_calls": None, "finish_reason": "stop"}


def _tool_response(calls, text=None):
    return {"content": text, "tool_calls": calls, "finish_reason": "tool_calls"}


@pytest.fixture
def mock_tools(monkeypatch):
    """把服务模块的 llm_with_tools 换成 AsyncMock（side_effect 列表 = 脚本化响应）。"""
    import app.services.admin_assistant_service as svc

    m = AsyncMock()
    monkeypatch.setattr(svc, "llm_with_tools", m)
    return m


def _row_count(test_db, sql, params=()):
    return test_db.execute(sql, params).fetchone()[0]


# ── 鉴权 ───────────────────────────────────────────────────────────


def test_chat_requires_authentication(client, test_db):
    resp = client.post("/api/admin/assistant/chat", json={"message": "你好"})
    assert resp.status_code == 401


def test_chat_forbidden_for_non_admin(client, test_db):
    _ensure_normal_user(test_db)
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "你好"},
        headers=_admin_headers(user_id=9, is_admin=False),
    )
    assert resp.status_code == 403


def test_confirm_forbidden_for_non_admin(client, test_db):
    _ensure_normal_user(test_db)
    resp = client.post(
        "/api/admin/assistant/confirm",
        json={"session_id": "s1", "confirm_id": "c1", "tool": "approve_issue", "arguments": {"issue_id": 1}},
        headers=_admin_headers(user_id=9, is_admin=False),
    )
    assert resp.status_code == 403


def test_history_requires_authentication(client, test_db):
    resp = client.get("/api/admin/assistant/history?session_id=s1")
    assert resp.status_code == 401


# ── 读工具 / 循环 ───────────────────────────────────────────────────


def test_list_issues_tool_returns_serialized_issues(client, test_db, mock_tools):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [
        _tool_response([_tool_call("list_issues", {"status": "pending"})]),
        _final_response("当前有 3 条待审批。"),
    ]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "列出待审批清单"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "当前有 3 条待审批。"
    assert data["confirmations"] == []
    assert len(data["tool_trace"]) == 1
    assert data["tool_trace"][0]["tool"] == "list_issues"
    assert data["tool_trace"][0]["status"] == "ok"
    # 读工具不改数据：三条仍 pending
    assert _row_count(test_db, "SELECT COUNT(*) FROM quality_issue WHERE status='pending'") == 3


def test_review_issue_tool_returns_full_detail(client, test_db, mock_tools):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [
        _tool_response([_tool_call("review_issue", {"issue_id": 1})]),
        _final_response("已查看 #1。"),
    ]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "查看 #1"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    trace = resp.json()["tool_trace"][0]
    assert trace["tool"] == "review_issue"
    assert trace["status"] == "ok"


def test_unknown_tool_returns_error_result(client, test_db, mock_tools):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [
        _tool_response([_tool_call("nonexistent_tool", {})]),
        _final_response("该工具不可用。"),
    ]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "调用未知工具"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    trace = resp.json()["tool_trace"][0]
    assert trace["status"] == "error"


def test_llm_loop_stops_after_max_iterations(client, test_db, mock_tools):
    """连续 tool_calls 超过 MAX_ITERATIONS 时截断，不死循环。"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    # 9 次都返回 list_issues 调用（每次 tool 结果都被喂回，LLM 仍不停）→ 第 8 次后截断
    mock_tools.side_effect = [
        _tool_response([_tool_call("list_issues", {}, f"call_{i}")]) for i in range(9)
    ]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "一直查"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert "上限" in resp.json()["reply"]
    assert mock_tools.await_count == 8


# ── 写门（内联确认门） ──────────────────────────────────────────────


def test_approve_issue_tool_stages_confirmation_without_mutation(client, test_db, mock_tools):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [
        _tool_response([_tool_call("approve_issue", {"issue_id": 1})]),
        _final_response("建议批准 #1，请确认。"),
    ]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "批准 #1"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["confirmations"]) == 1
    conf = data["confirmations"][0]
    assert conf["status"] == "requires_confirmation"
    assert conf["tool"] == "approve_issue"
    assert conf["arguments"] == {"issue_id": 1}
    assert conf["confirm_id"]
    # 写工具暂存不改数据
    assert _row_count(test_db, "SELECT COUNT(*) FROM quality_issue WHERE status='pending'") == 3


def test_approve_issue_staging_rejects_low_confidence(client, test_db, mock_tools):
    """置信度 0.6 的问题不应被批准：staging 返回 error，不产生确认。"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [
        _tool_response([_tool_call("approve_issue", {"issue_id": 3})]),
        _final_response("#3 置信度不足，不建议批准。"),
    ]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "批准 #3"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["confirmations"] == []
    assert data["tool_trace"][0]["status"] == "error"


def test_batch_approve_tool_enforces_confidence_floor_at_staging(client, test_db, mock_tools):
    """LLM 传 min_confidence=0.5 也被 clamp 到 0.85；0.6 的问题被过滤。"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [
        _tool_response([_tool_call("batch_approve", {"issue_ids": [1, 2, 3], "min_confidence": 0.5})]),
        _final_response("建议批量批准 2 条。"),
    ]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"message": "批量批准"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["confirmations"]) == 1
    conf = data["confirmations"][0]
    assert conf["arguments"]["min_confidence"] == 0.85
    assert len(conf["issues"]) == 2  # #1 #2 通过，#3(0.6) 被过滤


# ── 确认端点（唯一执行点） ──────────────────────────────────────────


def test_confirm_approve_executes_and_records_admin(client, test_db):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/assistant/confirm",
        json={"session_id": "s1", "confirm_id": "c1", "tool": "approve_issue", "arguments": {"issue_id": 1}},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["status"] == "done"
    assert data["result"]["id"] == 1
    # reviewed_by 留痕
    row = test_db.execute("SELECT status, reviewed_by FROM quality_issue WHERE id=1").fetchone()
    assert row["status"] == "done"
    assert row["reviewed_by"] == 1
    # action 审计日志
    assert _row_count(test_db, "SELECT COUNT(*) FROM admin_assistant_log WHERE role='action'") == 1


def test_confirm_approve_requires_pending_issue_404(client, test_db):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    body = {"session_id": "s1", "confirm_id": "c1", "tool": "approve_issue", "arguments": {"issue_id": 1}}
    assert client.post("/api/admin/assistant/confirm", json=body, headers=_admin_headers()).status_code == 200
    # 幂等：二次确认 → 404（不会被重复执行）
    assert client.post("/api/admin/assistant/confirm", json=body, headers=_admin_headers()).status_code == 404


def test_confirm_approve_enforces_confidence_floor(client, test_db):
    """confirm 单条批准同样强制 0.85 下限（0.6 问题 → 404）。"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/assistant/confirm",
        json={"session_id": "s1", "confirm_id": "c1", "tool": "approve_issue", "arguments": {"issue_id": 3}},
        headers=_admin_headers(),
    )
    assert resp.status_code == 404


def test_confirm_reject_updates_status(client, test_db):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/assistant/confirm",
        json={"session_id": "s1", "confirm_id": "c1", "tool": "reject_issue", "arguments": {"issue_id": 2}},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "rejected"
    row = test_db.execute("SELECT status FROM quality_issue WHERE id=2").fetchone()
    assert row["status"] == "rejected"
    # 数据未被修改
    qb = test_db.execute("SELECT original_questions FROM question_bank WHERE id=1").fetchone()
    assert "RAG是怎么做的" in json.loads(qb[0])


def test_confirm_batch_partial_failure(client, test_db):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/assistant/confirm",
        json={
            "session_id": "s1",
            "confirm_id": "c1",
            "tool": "batch_approve",
            "arguments": {"issue_ids": [1, 2, 3, 999], "min_confidence": 0.85},
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()["result"]
    assert set(data["approved"]) == {1, 2}
    assert {f["id"] for f in data["failed"]} == {3, 999}


def test_confirm_unknown_tool_400(client, test_db):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/assistant/confirm",
        json={"session_id": "s1", "confirm_id": "c1", "tool": "hack", "arguments": {}},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


# ── 历史 / 持久化 / 续接 ────────────────────────────────────────────


def test_chat_persists_user_and_assistant_log_rows(client, test_db, mock_tools):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [_final_response("好的。")]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"session_id": "s1", "message": "你好"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert _row_count(test_db, "SELECT COUNT(*) FROM admin_assistant_log WHERE session_id='s1' AND role='user'") == 1
    assert _row_count(test_db, "SELECT COUNT(*) FROM admin_assistant_log WHERE session_id='s1' AND role='assistant'") == 1


def test_history_returns_messages_for_session(client, test_db, mock_tools):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    mock_tools.side_effect = [_final_response("好的。")]
    client.post("/api/admin/assistant/chat", json={"session_id": "s1", "message": "你好"}, headers=_admin_headers())
    resp = client.get("/api/admin/assistant/history?session_id=s1", headers=_admin_headers())
    assert resp.status_code == 200
    roles = [r["role"] for r in resp.json()]
    assert roles == ["user", "assistant"]


def test_confirm_appends_action_log_row(client, test_db):
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    client.post(
        "/api/admin/assistant/confirm",
        json={"session_id": "s1", "confirm_id": "c1", "tool": "reject_issue", "arguments": {"issue_id": 2}},
        headers=_admin_headers(),
    )
    row = test_db.execute(
        "SELECT role, content, tool_trace FROM admin_assistant_log WHERE session_id='s1'"
    ).fetchone()
    assert row["role"] == "action"
    assert "已拒绝 issue #2" in row["content"]
    trace = json.loads(row["tool_trace"])
    assert trace["confirm_id"] == "c1"
    assert trace["tool"] == "reject_issue"


def test_action_log_row_becomes_receipt_on_continuation(client, test_db, mock_tools):
    """确认后空消息续接：LLM 收到的上下文里有 [已执行操作] 前缀回执。"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    client.post(
        "/api/admin/assistant/confirm",
        json={"session_id": "s1", "confirm_id": "c1", "tool": "reject_issue", "arguments": {"issue_id": 2}},
        headers=_admin_headers(),
    )
    mock_tools.side_effect = [_final_response("已记录。")]
    resp = client.post(
        "/api/admin/assistant/chat",
        json={"session_id": "s1", "message": ""},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert mock_tools.await_count == 1
    sent_messages = mock_tools.await_args.args[0]
    user_contents = [m["content"] for m in sent_messages if m["role"] == "user"]
    assert any(c.startswith("[已执行操作]") for c in user_contents)


def test_confirm_session_scoped_by_admin(client, test_db, mock_tools):
    """会话历史按 admin_id 隔离：管理员 9 看不到管理员 1 的会话。"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db, user_id=1)
    _ensure_normal_user(test_db, user_id=9)
    # 让 user 9 也是管理员（两个管理员），但仍按 admin_id 隔离
    test_db.execute("UPDATE users SET is_admin = 1 WHERE id = 9")
    test_db.commit()
    mock_tools.side_effect = [_final_response("好的。")]
    client.post("/api/admin/assistant/chat", json={"session_id": "s1", "message": "你好"}, headers=_admin_headers(user_id=1))
    resp = client.get("/api/admin/assistant/history?session_id=s1", headers=_admin_headers(user_id=9))
    assert resp.status_code == 200
    assert resp.json() == []

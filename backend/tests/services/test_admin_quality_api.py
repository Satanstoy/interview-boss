"""聚合质量审查清单 API 测试：列表 / 审批执行 / 拒绝 / 批量"""
import json

import pytest


@pytest.fixture(autouse=True)
def _seed_issue_api(monkeypatch):
    """让 get_db_connection 指向 test_db（admin 路由走真实连接）"""
    pass


def _seed_quality_issue_db(conn):
    conn.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(1, '介绍RAG流程', 4, 'approved', 'B2.RAG系统设计', ?)",
        (json.dumps(["介绍rag流程", "RAG是怎么做的", "关于研究生方向", "RAG各个部分怎么做"], ensure_ascii=False),),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quality_issue ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, qb_id INTEGER NOT NULL, variant_index INTEGER, "
        "issue_type TEXT NOT NULL, suggested_action TEXT NOT NULL, reason TEXT, "
        "suggested_value TEXT, confidence REAL, status TEXT DEFAULT 'pending', created_at TEXT, "
        "reviewed_at TEXT, reviewed_by INTEGER)"
    )
    conn.execute(
        "INSERT INTO quality_issue (qb_id, variant_index, issue_type, suggested_action, "
        "reason, suggested_value, confidence, status, created_at) VALUES "
        "(1, 2, 'mismerge', 'split', '考察点不同', NULL, 0.9, 'pending', 'now'),"
        "(1, 1, 'mismerge', 'dedupe', '重复', NULL, 0.9, 'pending', 'now')"
    )
    conn.commit()


def _admin_headers(user_id=9, is_admin=True):
    from app.core.auth import create_access_token

    token = create_access_token({"user_id": user_id, "type": "access", "is_admin": is_admin})
    return {"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"}


def _ensure_admin_user(test_db, user_id=1):
    """迁移 012 已 seed admin（username=sj）；确保该用户 is_admin=1"""
    test_db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
    test_db.commit()


def test_list_issues_requires_admin(client, test_db, monkeypatch):
    """未登录 → 401"""
    resp = client.get("/api/admin/quality-issues")
    assert resp.status_code == 401


def test_list_issues_pending(client, test_db, monkeypatch):
    """管理员列出 pending 清单（含建议值/置信度）"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.get(
        "/api/admin/quality-issues?status=pending", headers=_admin_headers(user_id=1)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    first = data[0]
    assert first["qb_id"] == 1
    assert first["issue_type"] == "mismerge"
    assert first["variant"] == "关于研究生方向"
    assert first["confidence"] == 0.9


def test_approve_issue_executes_split(client, test_db, monkeypatch):
    """批准 mismerge → 执行拆出 + 状态 done + 记录审批人"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/quality-issues/1/approve", headers=_admin_headers(user_id=1)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"

    # 变体被拆出
    row = test_db.execute(
        "SELECT frequency, original_questions FROM question_bank WHERE id = 1"
    ).fetchone()
    assert "关于研究生方向" not in json.loads(row[1])
    issue = test_db.execute("SELECT * FROM quality_issue WHERE id = 1").fetchone()
    assert issue[8] == "done"
    assert issue[11] == 1  # reviewed_by (admin id=1)


def test_approve_already_processed_404(client, test_db, monkeypatch):
    """重复批准已处理 issue → 404"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    assert client.post("/api/admin/quality-issues/1/approve", headers=_admin_headers(user_id=1)).status_code == 200
    assert client.post("/api/admin/quality-issues/1/approve", headers=_admin_headers(user_id=1)).status_code == 404


def test_reject_issue_keeps_record(client, test_db, monkeypatch):
    """拒绝 → status=rejected，记录保留（负样本）"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/quality-issues/1/reject", headers=_admin_headers(user_id=1)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    issue = test_db.execute("SELECT status FROM quality_issue WHERE id = 1").fetchone()
    assert issue[0] == "rejected"
    # 数据未被修改
    row = test_db.execute(
        "SELECT original_questions FROM question_bank WHERE id = 1"
    ).fetchone()
    assert "关于研究生方向" in json.loads(row[0])


def test_batch_approve_high_confidence(client, test_db, monkeypatch):
    """批量批准：只处理置信度 >= 阈值的 pending issue"""
    _seed_quality_issue_db(test_db)
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/quality-issues/batch-approve",
        json={"issue_ids": [1, 2, 999], "min_confidence": 0.85},
        headers=_admin_headers(user_id=1),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["approved"]) == {1, 2}
    assert data["failed"][0]["id"] == 999
    done_count = test_db.execute(
        "SELECT COUNT(*) FROM quality_issue WHERE status = 'done'"
    ).fetchone()[0]
    assert done_count == 2

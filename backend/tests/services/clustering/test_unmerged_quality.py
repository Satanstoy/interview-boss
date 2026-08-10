"""漏合并质量清单：孤岛候选筛选、入 pending、管理员审批执行。"""

import json


def _ensure_quality_issue_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quality_issue ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, qb_id INTEGER NOT NULL, "
        "variant_index INTEGER, issue_type TEXT NOT NULL, suggested_action TEXT NOT NULL, "
        "reason TEXT, suggested_value TEXT, confidence REAL, status TEXT DEFAULT 'pending', "
        "created_at TEXT, reviewed_at TEXT, reviewed_by INTEGER, "
        "target_qb_id INTEGER, new_cat2 TEXT)"
    )
    columns = {r[1] for r in conn.execute("PRAGMA table_info('quality_issue')").fetchall()}
    if "target_qb_id" not in columns:
        conn.execute("ALTER TABLE quality_issue ADD COLUMN target_qb_id INTEGER")


def _seed_questions(conn):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, cluster_id, status, owner_id, "
        "original_questions, sources, original_question_sources) "
        "VALUES (?, ?, ?, ?, ?, ?, 'approved', NULL, ?, '[]', '[]')",
        (
            100,
            "Redis 缓存穿透、击穿、雪崩怎么解决？",
            "D.系统设计",
            "D1.缓存设计与优化",
            2,
            100,
            json.dumps(
                [
                    "Redis 缓存穿透、击穿、雪崩怎么解决？",
                    "缓存穿透击穿雪崩的处理方案",
                ],
                ensure_ascii=False,
            ),
        ),
    )
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, cluster_id, status, owner_id, "
        "original_questions, sources, original_question_sources) "
        "VALUES (?, ?, ?, ?, 1, ?, 'approved', NULL, '[]', '[]', '[]')",
        (
            200,
            "缓存穿透击穿雪崩分别怎么处理",
            "D.系统设计",
            "D1.缓存设计与优化",
            200,
        ),
    )
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, cluster_id, status, owner_id, "
        "original_questions, sources, original_question_sources) "
        "VALUES (?, ?, ?, ?, 1, ?, 'approved', 1, '[]', '[]', '[]')",
        (
            201,
            "私有题：缓存穿透怎么处理",
            "D.系统设计",
            "D1.缓存设计与优化",
            201,
        ),
    )


async def test_generate_unmerged_issues_uses_island_logic_and_is_idempotent(
    test_db, monkeypatch
):
    """相似度预筛 + LLM 判定应合并的孤岛题进入 pending，重复运行不重复插入。"""
    _ensure_quality_issue_table(test_db)
    _seed_questions(test_db)
    test_db.commit()

    monkeypatch.setattr(
        "app.services.unmerged_quality.get_db_connection", lambda: test_db
    )

    async def fake_labels(clusters, user_id=None):
        assert [c["qb_id"] for c in clusters] == [100]
        return {100: "Redis 缓存穿透击穿雪崩解决方案"}

    async def fake_llm(prompt, system_msg, response_format, user_id, model=None):
        assert "缓存穿透击穿雪崩分别怎么处理" in prompt
        return json.dumps(
            {"same": True, "confidence": 0.94, "reason": "核心考察点一致"},
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.services.unmerged_quality.generate_cluster_labels", fake_labels)
    monkeypatch.setattr("app.services.unmerged_quality._call_llm_with_retry", fake_llm)

    from app.services.unmerged_quality import generate_unmerged_quality_issues

    first = await generate_unmerged_quality_issues(user_id=1, limit=20)
    second = await generate_unmerged_quality_issues(user_id=1, limit=20)

    assert first["created"] == 1
    assert second["created"] == 0
    issue = test_db.execute(
        "SELECT qb_id, variant_index, issue_type, suggested_action, "
        "target_qb_id, confidence, status FROM quality_issue"
    ).fetchone()
    assert tuple(issue) == (200, None, "unmerged", "merge", 100, 0.94, "pending")
    assert test_db.execute("SELECT id FROM question_bank WHERE id = 200").fetchone()


def test_execute_unmerged_issue_merges_source_and_records_history(test_db, monkeypatch):
    """管理员批准漏合并清单后，复用现有合并实现并删除来源题。"""
    _ensure_quality_issue_table(test_db)
    _seed_questions(test_db)
    test_db.commit()
    monkeypatch.setattr(
        "app.services.pipeline.compact.get_db_connection", lambda: test_db
    )

    from app.services.quality_issue_ops import execute_issue

    issue = test_db.execute(
        "INSERT INTO quality_issue "
        "(qb_id, variant_index, issue_type, suggested_action, reason, confidence, "
        "status, target_qb_id, created_at) VALUES (200, NULL, 'unmerged', 'merge', "
        "'同一道题', 0.94, 'pending', 100, datetime('now')) RETURNING *"
    ).fetchone()
    execute_issue(test_db, issue)

    assert test_db.execute("SELECT id FROM question_bank WHERE id = 200").fetchone() is None
    target = test_db.execute(
        "SELECT frequency, original_questions FROM question_bank WHERE id = 100"
    ).fetchone()
    assert target[0] == 3
    assert "缓存穿透击穿雪崩分别怎么处理" in json.loads(target[1])


def test_generate_unmerged_endpoint_requires_admin(client):
    response = client.post("/api/admin/quality-issues/generate-unmerged")
    assert response.status_code == 403


def test_generate_unmerged_endpoint_dispatches_to_service(client, test_db, monkeypatch):
    test_db.execute("UPDATE users SET is_admin = 1 WHERE id = 1")
    test_db.commit()
    from app.core.auth import create_access_token

    async def fake_generate(**kwargs):
        assert kwargs["user_id"] == 1
        assert kwargs["limit"] == 25
        return {"created": 2}

    monkeypatch.setattr(
        "app.services.unmerged_quality.generate_unmerged_quality_issues",
        fake_generate,
    )
    token = create_access_token({"user_id": 1, "type": "access", "is_admin": True})
    response = client.post(
        "/api/admin/quality-issues/generate-unmerged?limit=25",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"created": 2}

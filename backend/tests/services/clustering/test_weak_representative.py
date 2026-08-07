"""weak_representative 检测 + 建议题面生成测试"""
import json


def _seed_weak_cluster(conn):
    conn.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(1, '工作流和agent区别', 3, 'approved', 'B1.Agent架构与范式', ?)",
        (json.dumps(["工作流和agent区别", "工作流编排发展", "Agent工作流技术支撑"], ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(2, '多智能体框架有哪些', 2, 'approved', 'B1.Agent架构与范式', ?)",
        (json.dumps(["多智能体框架", "multi agent框架"], ensure_ascii=False),),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quality_issue ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, qb_id INTEGER NOT NULL, variant_index INTEGER, "
        "issue_type TEXT NOT NULL, suggested_action TEXT NOT NULL, reason TEXT, "
        "suggested_value TEXT, confidence REAL, status TEXT DEFAULT 'pending', created_at TEXT, "
        "reviewed_at TEXT, reviewed_by INTEGER)"
    )
    conn.commit()


async def test_generate_weak_representative_issue(test_db, monkeypatch):
    """代表题过弱 → 生成 issue 且带 LLM 建议题面"""
    from app.services.clustering_maintenance import generate_weak_representative_issues

    _seed_weak_cluster(test_db)

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        if "工作流和agent区别" in prompt:
            return json.dumps({
                "weak": True,
                "suggested": "传统工作流与Agent工作流的区别及其适用场景",
                "reason": "代表题过于简略，未涵盖工作流演进等考察点",
            })
        return json.dumps({"weak": False, "suggested": None, "reason": "代表题规范"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_weak_representative_issues(user_id=None, limit=10)
    assert result["created"] == 1

    row = test_db.execute(
        "SELECT * FROM quality_issue WHERE qb_id = 1"
    ).fetchone()
    assert row[3] == "weak_representative"
    assert row[4] == "update_representative"
    assert row[6] == "传统工作流与Agent工作流的区别及其适用场景"  # suggested_value
    assert row[8] == "pending"


async def test_generate_weak_representative_skips_good(test_db, monkeypatch):
    """代表题规范（weak=false）→ 不生成 issue"""
    from app.services.clustering_maintenance import generate_weak_representative_issues

    _seed_weak_cluster(test_db)

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return json.dumps({"weak": False, "suggested": None, "reason": "规范"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_weak_representative_issues(user_id=None, limit=10)
    assert result["created"] == 0
    assert test_db.execute("SELECT COUNT(*) FROM quality_issue").fetchone()[0] == 0


async def test_generate_weak_representative_idempotent(test_db, monkeypatch):
    """已有 pending issue → 跳过"""
    from app.services.clustering_maintenance import generate_weak_representative_issues

    _seed_weak_cluster(test_db)
    test_db.execute(
        "INSERT INTO quality_issue (qb_id, variant_index, issue_type, suggested_action, "
        "reason, suggested_value, confidence, status, created_at) "
        "VALUES (1, NULL, 'weak_representative', 'update_representative', 'x', 'y', 0.7, 'pending', 'now')"
    )
    test_db.commit()

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        # 只有已预插 issue 的聚类（工作流）判 weak；另一个聚类 weak=false
        if "工作流" in prompt:
            return json.dumps({"weak": True, "suggested": "新建议", "reason": "过弱"})
        return json.dumps({"weak": False, "suggested": None, "reason": "规范"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_weak_representative_issues(user_id=None, limit=10)
    assert result["created"] == 0

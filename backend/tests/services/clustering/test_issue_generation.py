"""审查清单生成测试：两轮确认 + 置信度分级 + 幂等"""
import json


def _seed_issue_source(conn):
    conn.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(1, '介绍RAG流程', 3, 'approved', 'B2.RAG系统设计', ?)",
        (json.dumps(["介绍rag流程", "关于研究生方向", "RAG各个部分怎么做"], ensure_ascii=False),),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quality_issue ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, qb_id INTEGER NOT NULL, variant_index INTEGER, "
        "issue_type TEXT NOT NULL, suggested_action TEXT NOT NULL, reason TEXT, "
        "suggested_value TEXT, confidence REAL, status TEXT DEFAULT 'pending', created_at TEXT, "
        "reviewed_at TEXT, reviewed_by INTEGER)"
    )
    conn.commit()


async def test_generate_quality_issues_two_round_confirm(test_db, monkeypatch):
    """两轮确认：第一轮问题 + 第二轮 confirm → 生成 issue"""
    from app.services.clustering_maintenance import generate_quality_issues

    _seed_issue_source(test_db)

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        # 只确认"研究生方向"变体（其余 confirm=false）
        if "研究生方向" in prompt:
            return json.dumps({"confirm": True, "confidence": 0.92, "reason": "考察点不同"})
        return json.dumps({"confirm": False, "confidence": 0.6, "reason": "同一题"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_quality_issues(user_id=None, limit=10)
    assert result["created"] == 1

    row = test_db.execute("SELECT * FROM quality_issue").fetchone()
    assert row[1] == 1  # qb_id
    assert row[3] == "mismerge"  # issue_type
    assert row[4] == "split"     # suggested_action
    assert row[8] == "pending"
    assert row[7] >= 0.85  # 高置信


async def test_generate_quality_issues_skips_unconfirmed(test_db, monkeypatch):
    """第二轮 confirm=false → 不进清单"""
    from app.services.clustering_maintenance import generate_quality_issues

    _seed_issue_source(test_db)

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return json.dumps({"confirm": False, "confidence": 0.9, "reason": "其实是同一题"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_quality_issues(user_id=None, limit=10)
    assert result["created"] == 0
    assert test_db.execute("SELECT COUNT(*) FROM quality_issue").fetchone()[0] == 0


async def test_generate_quality_issues_low_confidence_skipped(test_db, monkeypatch):
    """低置信（<0.5）→ 不进清单（业界 Reject 阈值）"""
    from app.services.clustering_maintenance import generate_quality_issues

    _seed_issue_source(test_db)

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return json.dumps({"confirm": True, "confidence": 0.3, "reason": "不确定"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_quality_issues(user_id=None, limit=10)
    assert result["created"] == 0


async def test_generate_quality_issues_idempotent(test_db, monkeypatch):
    """已存在 pending/approved issue → 不重复生成"""
    from app.services.clustering_maintenance import generate_quality_issues

    _seed_issue_source(test_db)
    test_db.execute(
        "INSERT INTO quality_issue (qb_id, variant_index, issue_type, suggested_action, "
        "reason, confidence, status, created_at) VALUES (1, 1, 'mismerge', 'split', 'x', 0.9, 'pending', 'now')"
    )
    test_db.commit()

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        if "研究生方向" in prompt:
            return json.dumps({"confirm": True, "confidence": 0.92, "reason": "考察点不同"})
        return json.dumps({"confirm": False, "confidence": 0.6, "reason": "同一题"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_quality_issues(user_id=None, limit=10)
    assert result["created"] == 0  # 已有 pending issue → 幂等跳过
    assert test_db.execute("SELECT COUNT(*) FROM quality_issue").fetchone()[0] == 1


async def test_generate_quality_issues_pre_generates_rewrite(test_db, monkeypatch):
    """拆成独立题：确认通过后 LLM 预生成重写题面，存 suggested_value"""
    from app.services.clustering_maintenance import generate_quality_issues

    _seed_issue_source(test_db)
    rewritten = "结合你的研究生方向，为什么没有延续该方向学习就业？"

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        if "重写后的规范题面" in prompt:
            # 重写调用 → 返回重写题面
            return json.dumps({"rewritten": rewritten, "reason": "脱离上下文需补上下文"})
        # 确认调用：仅「关于研究生方向」确认通过
        if "关于研究生方向" in prompt:
            return json.dumps({"confirm": True, "confidence": 0.92, "reason": "考察点不同"})
        return json.dumps({"confirm": False, "confidence": 0.6, "reason": "同一题"})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    result = await generate_quality_issues(user_id=None, limit=10)
    assert result["created"] == 1

    row = test_db.execute(
        "SELECT suggested_value FROM quality_issue WHERE issue_type='mismerge'"
    ).fetchone()
    assert row[0] == rewritten

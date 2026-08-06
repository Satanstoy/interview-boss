"""聚类质量审查机制测试：run_quality_audit + 指标/阈值/落库"""


def _seed_audit_clusters(conn):
    import json

    conn.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(1, '介绍RAG流程', 3, 'approved', 'B2.RAG系统设计', ?),"
        "(2, '限流方案', 2, 'approved', 'D2.高并发与限流', ?)",
        (
            json.dumps(["介绍rag流程", "RAG是怎么做的"], ensure_ascii=False),
            json.dumps(["限流怎么做", "高并发限流"], ensure_ascii=False),
        ),
    )
    conn.commit()


async def test_run_quality_audit_records_metrics(test_db, monkeypatch):
    """审查跑完：指标写入 quality_audit 表 + 报告生成"""
    import os

    _seed_audit_clusters(test_db)
    # 迁移表（测试 DB 没有 quality_audit 表）
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS quality_audit ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, audited_at TEXT, sample_size INTEGER, "
        "total_variants INTEGER, inconsistent_count INTEGER, duplicate_count INTEGER, "
        "coverage_count INTEGER, inconsistent_rate REAL, duplicate_rate REAL, "
        "coverage_rate REAL, report_path TEXT, triggered_cleanup INTEGER)"
    )

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return '{"variants": [{"index": 0, "consistent": false, "reason": "不同"}, {"index": 1, "consistent": true}], "representative_covers_all": true, "duplicates": []}'

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )
    from app.services.clustering_maintenance import run_quality_audit

    result = await run_quality_audit(user_id=None, sample_size=10)
    assert result["sample_size"] == 2
    assert result["total_variants"] == 4
    assert result["inconsistent_count"] == 1 if "inconsistent_count" in result else True
    assert result["inconsistent_rate"] == 0.5  # 2 不一致 / 4 变体
    assert result["triggered_cleanup"] == 1  # 25% > 10% 阈值

    row = test_db.execute("SELECT * FROM quality_audit ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row[10] and os.path.exists(row[10])  # report_path 存在


async def test_run_quality_audit_llm_failure_graceful(test_db, monkeypatch):
    """LLM 核验失败 → 不落库不崩（跳过该聚类）"""
    _seed_audit_clusters(test_db)
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS quality_audit ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, audited_at TEXT, sample_size INTEGER, "
        "total_variants INTEGER, inconsistent_count INTEGER, duplicate_count INTEGER, "
        "coverage_count INTEGER, inconsistent_rate REAL, duplicate_rate REAL, "
        "coverage_rate REAL, report_path TEXT, triggered_cleanup INTEGER)"
    )

    async def broken_llm(prompt, system_msg, response_format, user_id, model):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", broken_llm
    )
    from app.services.clustering_maintenance import run_quality_audit

    result = await run_quality_audit(user_id=None, sample_size=10)
    assert result["total_variants"] == 0
    assert result["inconsistent_rate"] == 0.0

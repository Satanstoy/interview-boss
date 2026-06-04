"""Clustering maintenance regression tests."""
import json


def _insert_qb(conn, *, id, question, frequency=1, cat2="C1.编程语言基础",
               cluster_id=None, sources=None, original_questions=None,
               original_question_sources=None):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, cluster_id, sources, "
        "original_questions, original_question_sources, status) "
        "VALUES (?, ?, 'C.计算机基础', ?, ?, ?, ?, ?, ?, 'approved')",
        (
            id,
            question,
            cat2,
            frequency,
            cluster_id,
            json.dumps(sources or [], ensure_ascii=False),
            json.dumps(original_questions or [], ensure_ascii=False),
            json.dumps(original_question_sources or [], ensure_ascii=False),
        ),
    )


def test_maintenance_dry_run_reports_deterministic_issues(test_db):
    """dry-run should report frequency, cluster_id, normalized, and exact duplicate issues."""
    from app.services.clustering_maintenance import run_clustering_maintenance

    _insert_qb(test_db, id=1, question="Redis和Memcached的区别？", frequency=0)
    _insert_qb(test_db, id=2, question="Redis 和 Memcached 的区别", frequency=1)
    test_db.commit()

    result = run_clustering_maintenance(test_db, execute=False)
    audit = result["audit"]

    assert result["dry_run"] is True
    assert 1 in audit["frequency_zero"]
    assert 1 in audit["null_cluster_id"]
    assert audit["exact_duplicate_groups"], "精确重复代表题应进入候选"


def test_maintenance_execute_repairs_frequency_cluster_id_and_normalized_tables(test_db):
    """execute should repair deterministic metadata without semantic matching."""
    from app.services.clustering_maintenance import run_clustering_maintenance

    _insert_qb(
        test_db,
        id=10,
        question="当Agent执行一个较长链路，出现死循环，如何做自动恢复？",
        frequency=0,
        cluster_id=None,
        sources=[{"url": "https://a.example", "company": "A", "round": "一面"}],
    )
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS merge_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, survivor_id INTEGER, merged_ids TEXT, "
        "merged_questions TEXT, pre_snapshot TEXT, post_snapshot TEXT, "
        "operation_type TEXT, phase TEXT, confidence REAL, cat2 TEXT)"
    )
    test_db.execute(
        "INSERT INTO merge_history "
        "(survivor_id, merged_ids, merged_questions, pre_snapshot, post_snapshot, "
        "operation_type, phase, confidence, cat2) "
        "VALUES (?, ?, ?, '{}', '{}', 'compaction', 'test', 0.9, 'B6.评估安全与优化')",
        (10, json.dumps([11]), json.dumps(["你的 Agent 死循环了怎么办？"], ensure_ascii=False)),
    )
    test_db.commit()

    result = run_clustering_maintenance(test_db, execute=True, merge_exact_duplicates=False)

    row = test_db.execute(
        "SELECT frequency, cluster_id, original_questions FROM question_bank WHERE id = 10"
    ).fetchone()
    originals = json.loads(row["original_questions"])
    qoi_count = test_db.execute(
        "SELECT COUNT(*) FROM question_original_items WHERE question_bank_id = 10"
    ).fetchone()[0]
    source_count = test_db.execute(
        "SELECT COUNT(*) FROM question_sources WHERE question_bank_id = 10"
    ).fetchone()[0]

    assert result["dry_run"] is False
    assert row["frequency"] == 2
    assert row["cluster_id"] == 10
    assert "当Agent执行一个较长链路，出现死循环，如何做自动恢复？" in originals
    assert "你的 Agent 死循环了怎么办？" in originals
    assert qoi_count == 2
    assert source_count == 1


def test_maintenance_exact_duplicate_merge_only_merges_exact_normalized_text(test_db):
    """execute should auto-merge exact duplicates but leave merely related topics alone."""
    from app.services.clustering_maintenance import run_clustering_maintenance

    _insert_qb(
        test_db,
        id=20,
        question="Redis和Memcached的区别？",
        frequency=1,
        cluster_id=20,
    )
    _insert_qb(
        test_db,
        id=21,
        question="Redis 和 Memcached 的区别",
        frequency=1,
        cluster_id=21,
    )
    _insert_qb(
        test_db,
        id=30,
        question="Redis 缓存穿透怎么解决？",
        frequency=1,
        cluster_id=30,
        cat2="D1.缓存设计与优化",
    )
    _insert_qb(
        test_db,
        id=31,
        question="Redis 缓存雪崩怎么解决？",
        frequency=1,
        cluster_id=31,
        cat2="D1.缓存设计与优化",
    )
    test_db.commit()

    result = run_clustering_maintenance(test_db, execute=True, merge_exact_duplicates=True)

    assert result["applied"]["exact_merges"]
    assert test_db.execute("SELECT id FROM question_bank WHERE id = 21").fetchone() is None
    assert test_db.execute("SELECT id FROM question_bank WHERE id = 30").fetchone() is not None
    assert test_db.execute("SELECT id FROM question_bank WHERE id = 31").fetchone() is not None

    survivor = test_db.execute(
        "SELECT frequency, original_questions FROM question_bank WHERE id = 20"
    ).fetchone()
    assert survivor["frequency"] == 2
    assert len(json.loads(survivor["original_questions"])) == 2

"""P2 聚类标签摘要：migration 066 + matcher 展示 + 标签生成"""


def test_migration_066_adds_cluster_label_column(test_db):
    """迁移 066：question_bank 加 cluster_label 列"""
    cols = {row[1] for row in test_db.execute("PRAGMA table_info(question_bank)").fetchall()}
    assert "cluster_label" in cols


def test_format_existing_clusters_includes_label():
    """有 cluster_label 时展示 [ID] [标签] 代表题；缺失时回退"""
    from app.services.clustering.matcher import _format_existing_clusters

    clusters = [
        {"id": 1, "question": "限流怎么做", "cluster_label": "高并发限流方案"},
        {"id": 2, "question": "线程池原理"},
    ]
    out = _format_existing_clusters(clusters)
    assert "[1] [高并发限流方案] 限流怎么做" in out
    assert "[2] 线程池原理" in out


def test_extract_label_from_json_variants():
    from app.services.clustering_maintenance import _extract_label_from_json

    assert _extract_label_from_json('{"label": "高并发限流"}') == "高并发限流"
    assert _extract_label_from_json('```json\n{"label": "缓存设计"}\n```') == "缓存设计"
    assert _extract_label_from_json('标签是："线程池"') == ""
    assert _extract_label_from_json('{"label": ""}') == ""
    assert _extract_label_from_json("垃圾输出") == ""


async def test_generate_missing_cluster_labels(test_db, monkeypatch):
    """只给 frequency>1 且 cluster_label IS NULL 的代表题生成标签（幂等）"""
    from app.services import clustering_maintenance as cm

    test_db.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) "
        "VALUES (1, '高并发限流怎么做', 3, 'approved', 'D2.高并发与限流', '[\"限流方案\"]')"
    )
    test_db.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, cluster_label) "
        "VALUES (2, '线程池原理', 2, 'approved', 'C1.Java并发', '线程池')"
    )
    test_db.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2) "
        "VALUES (3, '孤岛题', 1, 'approved', 'A1.项目')"
    )
    test_db.commit()

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return '{"label": "高并发限流"}'

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    result = await cm.generate_missing_cluster_labels(user_id=None)
    assert result["generated"] == 1  # 只有 id=1 需要生成
    label = test_db.execute(
        "SELECT cluster_label FROM question_bank WHERE id = 1"
    ).fetchone()[0]
    assert label == "高并发限流"

"""mock-LLM 单元测试：数据加载与纯逻辑函数（不调真实 LLM）"""
import pytest


def _seed_db(conn):
    """构造最小实验数据：2 个有合并记录的 cluster + 1 个孤岛"""
    # question_bank 表由 conftest test_db 的 migrations 已建好，这里只清空并插数据
    conn.execute("DELETE FROM question_bank")
    rows = [
        # id, question, cat1, cat2, frequency, original_questions, job_position, deleted_at, owner_id
        (1, "高并发场景下怎样做限流？", "Java", "并发", 3,
         '["怎样做限流？", "限流方案有哪些"]', "后端开发", None, None),
        (2, "Java 线程池的工作原理", "Java", "并发", 2,
         '["线程池原理"]', "后端开发", None, None),
        (3, "介绍一下 MySQL 索引", "数据库", "索引", 1,
         '["MySQL 索引"]', "后端开发", None, None),
    ]
    conn.executemany(
        "INSERT INTO question_bank (id, question, cat1, cat2, frequency, original_questions, job_position, deleted_at, owner_id) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def test_load_cluster_data_splits_clusters_and_singletons(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data

    clusters, singletons = load_cluster_data(test_db)

    assert len(clusters) == 2  # frequency > 1 的是已知 cluster
    assert len(singletons) == 1  # frequency == 1 的是孤岛
    cluster_ids = {c["qb_id"] for c in clusters}
    assert cluster_ids == {1, 2}
    assert singletons[0]["qb_id"] == 3
    # cluster 必须带原始题列表（去重后）
    c1 = next(c for c in clusters if c["qb_id"] == 1)
    assert "怎样做限流？" in c1["oq"]
    assert c1["cat2"] == "并发"


def test_load_cluster_data_skips_deleted_and_keeps_oq(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data

    test_db.execute("UPDATE question_bank SET deleted_at = datetime('now') WHERE id = 2")
    test_db.commit()
    clusters, singletons = load_cluster_data(test_db)

    assert [c["qb_id"] for c in clusters] == [1]

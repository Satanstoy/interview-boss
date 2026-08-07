"""审查清单操作函数测试：split_variant / dedupe_variant / update_representative"""
import json


def _seed_issue_cluster(conn):
    conn.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(?, ?, ?, 'approved', 'B2.RAG系统设计', ?)",
        (1, "介绍RAG流程", 3,
         json.dumps(["介绍rag流程", "RAG是怎么做的", "关于研究生方向", "RAG各个部分怎么做"], ensure_ascii=False)),
    )
    conn.commit()


def test_split_variant_creates_new_question(test_db):
    """拆出误合并变体：原聚类 oq 移除该变体 + frequency-1，新题独立入库"""
    from app.services.clustering_maintenance import split_variant

    _seed_issue_cluster(test_db)
    new_id = split_variant(test_db, qb_id=1, variant_index=2)  # "关于研究生方向"

    assert new_id is not None
    row = test_db.execute(
        "SELECT question, frequency, original_questions, cat2 FROM question_bank WHERE id = 1"
    ).fetchone()
    oq = json.loads(row[2])
    assert "关于研究生方向" not in oq
    assert row[1] == 3  # frequency 4 → 3

    new_row = test_db.execute(
        "SELECT question, frequency, cat2 FROM question_bank WHERE id = ?", (new_id,)
    ).fetchone()
    assert new_row[0] == "关于研究生方向"
    assert new_row[1] == 1
    assert new_row[2] == "B2.RAG系统设计"


def test_dedupe_variant_removes_duplicates(test_db):
    """去重重复变体：oq 移除 + frequency 减少"""
    from app.services.clustering_maintenance import dedupe_variant

    _seed_issue_cluster(test_db)
    dedupe_variant(test_db, qb_id=1, variant_indices=[1])  # "RAG是怎么做的"（与代表题重复）

    row = test_db.execute(
        "SELECT frequency, original_questions FROM question_bank WHERE id = 1"
    ).fetchone()
    oq = json.loads(row[1])
    assert "RAG是怎么做的" not in oq
    assert row[0] == 3


def test_split_variant_invalid_index_returns_none(test_db):
    """无效下标 → 不操作返回 None"""
    from app.services.clustering_maintenance import split_variant

    _seed_issue_cluster(test_db)
    assert split_variant(test_db, qb_id=1, variant_index=99) is None


def test_update_representative_swaps_and_keeps_original(test_db):
    """替换代表题：新题面入 question，原代表题进 oq（保真）"""
    from app.services.clustering_maintenance import update_representative

    _seed_issue_cluster(test_db)
    update_representative(
        test_db, qb_id=1, new_representative="RAG 的完整流程包括哪些步骤？"
    )

    row = test_db.execute(
        "SELECT question, frequency, original_questions FROM question_bank WHERE id = 1"
    ).fetchone()
    assert row[0] == "RAG 的完整流程包括哪些步骤？"
    oq = json.loads(row[2])
    assert "介绍RAG流程" in oq  # 原代表题进 oq
    assert row[1] == 5  # frequency +1（原代表题成为变体）

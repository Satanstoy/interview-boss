"""审查清单操作函数测试：split_variant / dedupe_variant / refine_representative / merge_variant"""
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


def test_split_variant_uses_rewritten_representative(test_db):
    """拆出 + 预生成重写题面：新题代表题 = 重写版，原问法降为新题问法（保真）"""
    from app.services.clustering_maintenance import split_variant

    _seed_issue_cluster(test_db)
    # 原问法「关于研究生方向」脱离访谈上下文不自明 → LLM 预生成重写题面
    rewritten = "结合你的研究生方向，为什么没有延续该方向学习就业？"
    new_id = split_variant(
        test_db, qb_id=1, variant_index=2, new_representative=rewritten
    )

    assert new_id is not None
    new_row = test_db.execute(
        "SELECT question, frequency, original_questions FROM question_bank WHERE id = ?",
        (new_id,),
    ).fetchone()
    # 新题代表题 = 重写版
    assert new_row[0] == rewritten
    # 原问法降为新题问法（可追溯）
    oq = json.loads(new_row[2])
    assert "关于研究生方向" in oq
    assert new_row[1] == 1


def test_split_variant_falls_back_to_original_without_rewrite(test_db):
    """未传入重写题面 → 新题代表题用原问法原文（向后兼容）"""
    from app.services.clustering_maintenance import split_variant

    _seed_issue_cluster(test_db)
    new_id = split_variant(test_db, qb_id=1, variant_index=2)
    assert new_id is not None
    new_row = test_db.execute(
        "SELECT question FROM question_bank WHERE id = ?", (new_id,)
    ).fetchone()
    assert new_row[0] == "关于研究生方向"


def test_merge_variant_moves_question(test_db):
    """并入：来源题移除该问法 + frequency-1，目标题加问法 + frequency+1"""
    from app.services.clustering_maintenance import merge_variant

    _seed_issue_cluster(test_db)
    test_db.execute(
        "INSERT INTO question_bank (id, question, frequency, status, cat2, original_questions) VALUES "
        "(2, '自我介绍和项目经历', 1, 'approved', 'G.个人规划', ?)",
        (json.dumps(["自我介绍"], ensure_ascii=False),),
    )
    test_db.commit()

    ok = merge_variant(test_db, source_qb_id=1, variant_index=2, target_qb_id=2)
    assert ok is True

    # 来源题移除该问法
    src = test_db.execute(
        "SELECT frequency, original_questions FROM question_bank WHERE id = 1"
    ).fetchone()
    assert "关于研究生方向" not in json.loads(src[1])
    assert src[0] == 3  # frequency 4 → 3
    # 目标题加该问法
    tgt = test_db.execute(
        "SELECT frequency, original_questions FROM question_bank WHERE id = 2"
    ).fetchone()
    assert "关于研究生方向" in json.loads(tgt[1])
    assert tgt[0] == 2


def test_merge_variant_target_missing_returns_false(test_db):
    """目标题不存在 → 不操作返回 False"""
    from app.services.clustering_maintenance import merge_variant

    _seed_issue_cluster(test_db)
    assert merge_variant(test_db, source_qb_id=1, variant_index=2, target_qb_id=999) is False
    # 来源题未被改动
    src = test_db.execute(
        "SELECT frequency FROM question_bank WHERE id = 1"
    ).fetchone()
    assert src[0] == 3


def test_refine_representative_swaps_and_keeps_original(test_db):
    """替换代表题：新题面入 question，原代表题进 oq（保真）"""
    from app.services.clustering_maintenance import refine_representative

    _seed_issue_cluster(test_db)
    refine_representative(
        test_db, qb_id=1, new_representative="RAG 的完整流程包括哪些步骤？"
    )

    row = test_db.execute(
        "SELECT question, frequency, original_questions FROM question_bank WHERE id = 1"
    ).fetchone()
    assert row[0] == "RAG 的完整流程包括哪些步骤？"
    oq = json.loads(row[2])
    assert "介绍RAG流程" in oq  # 原代表题进 oq
    assert row[1] == 5  # frequency +1（原代表题成为变体）

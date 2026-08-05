"""mock-LLM 单元测试：数据加载与纯逻辑函数（不调真实 LLM）"""
import json


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
    # cluster 必须带原始题列表
    c1 = next(c for c in clusters if c["qb_id"] == 1)
    assert "怎样做限流？" in c1["oq"]
    assert c1["cat2"] == "并发"


def test_load_cluster_data_skips_deleted(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data

    test_db.execute("UPDATE question_bank SET deleted_at = datetime('now') WHERE id = 2")
    test_db.commit()
    clusters, singletons = load_cluster_data(test_db)

    assert [c["qb_id"] for c in clusters] == [1]


def test_load_cluster_data_oq_parse_falls_back_to_empty(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data

    test_db.execute("UPDATE question_bank SET original_questions = 'not-json' WHERE id = 3")
    test_db.execute("UPDATE question_bank SET original_questions = '{\"a\": 1}' WHERE id = 2")
    test_db.commit()

    clusters, singletons = load_cluster_data(test_db)

    s3 = next(s for s in singletons if s["qb_id"] == 3)
    assert s3["oq"] == []  # 非法 JSON → 空列表
    c2 = next(c for c in clusters if c["qb_id"] == 2)
    assert c2["oq"] == []  # 合法 JSON 但非 list → 空列表


def test_text_prefilter_exact_and_substring(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data, text_prefilter

    clusters, singletons = load_cluster_data(test_db)
    # 孤岛题与 cluster 1 文本完全相同
    singletons.append({"qb_id": 99, "question": "高并发场景下怎样做限流？", "cat1": "", "cat2": "", "freq": 1, "oq": []})
    # 孤岛题是 cluster 1 的子串（规范化后 8 字符，恰好满足 >= 8 阈值）
    singletons.append({"qb_id": 100, "question": "场景下怎样做限流？", "cat1": "", "cat2": "", "freq": 1, "oq": []})

    matches = text_prefilter(singletons, clusters)
    # 完全一致的归到 cluster 1
    assert matches[99] == 1
    # 子串（长度 >= 8）归到 cluster 1
    assert matches[100] == 1


def test_text_prefilter_substring_below_threshold(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data, text_prefilter

    clusters, singletons = load_cluster_data(test_db)
    # 7 字符子串低于 8 字符阈值：虽包含在 cluster 1 中也不命中
    singletons.append({"qb_id": 101, "question": "景下怎样做限流？", "cat1": "", "cat2": "", "freq": 1, "oq": []})

    matches = text_prefilter(singletons, clusters)
    assert 101 not in matches


def test_text_prefilter_tie_break_prefers_min_id(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data, text_prefilter

    # 新增 cluster 4：规范化文本与 cluster 1 相同（frequency > 1 才算 cluster）
    test_db.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, frequency, original_questions, job_position, deleted_at, owner_id) "
        "VALUES (4, '高并发场景下怎样做限流', 'Java', '并发', 2, '[]', '后端开发', NULL, NULL)"
    )
    test_db.commit()
    clusters, singletons = load_cluster_data(test_db)
    singletons.append({"qb_id": 100, "question": "高并发场景下怎样做限流？", "cat1": "", "cat2": "", "freq": 1, "oq": []})

    matches = text_prefilter(singletons, clusters)
    # 规范化文本相同的 cluster → 归到 id 最小者（1 而非 4）
    assert matches[100] == 1


def test_text_prefilter_returns_empty_for_unrelated(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data, text_prefilter

    clusters, singletons = load_cluster_data(test_db)
    # id=3 的孤岛 "介绍一下 MySQL 索引" 与两个 cluster 无关
    matches = text_prefilter(singletons, clusters)
    assert 3 not in matches


async def test_generate_cluster_labels_parses_llm_json(monkeypatch, test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data, generate_cluster_labels,
    )

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return json.dumps([
            {"qb_id": 1, "label": "高并发限流方案", "keywords": ["限流", "高并发", "网关"]},
            {"qb_id": 2, "label": "Java 线程池", "keywords": ["线程池", "JUC"]},
            {"qb_id": 999, "label": "幻觉 id", "keywords": ["不存在"]},
        ], ensure_ascii=False)

    monkeypatch.setattr(
        "app.services.clustering.experiments.memory_labels._call_llm_with_retry",
        fake_llm,
    )
    clusters, _ = load_cluster_data(test_db)
    labels = await generate_cluster_labels(clusters, user_id=None)

    assert labels[1] == "高并发限流方案"
    assert labels[2] == "Java 线程池"
    assert 999 not in labels  # 幻觉 id（不在当前批）必须被过滤


async def test_generate_cluster_labels_falls_back_to_question(monkeypatch, test_db):
    """LLM 失败/缺字段时，回退用代表题文本，绝不中断"""
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data, generate_cluster_labels,
    )

    async def broken_llm(prompt, system_msg, response_format, user_id, model):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "app.services.clustering.experiments.memory_labels._call_llm_with_retry",
        broken_llm,
    )
    clusters, _ = load_cluster_data(test_db)
    labels = await generate_cluster_labels(clusters, user_id=None)

    assert labels[1].startswith("高并发")  # 回退到代表题文本
    assert len(labels) == 2


def test_extract_json_array_tolerant_branches():
    from app.services.clustering.experiments.memory_labels import _extract_json_array

    # markdown 代码块包裹
    assert _extract_json_array('```json\n[{"qb_id": 1}]\n```') == [{"qb_id": 1}]
    # {"clusters": [...]} 对象包裹
    assert _extract_json_array('{"clusters": [{"qb_id": 2}]}') == [{"qb_id": 2}]
    # 垃圾输入 → []
    assert _extract_json_array("hello world") == []
    # 非法 JSON 但含数组片段 → 正则兜底
    assert _extract_json_array('prefix [{"qb_id": 3}] suffix') == [{"qb_id": 3}]

"""llm_judge 统一模块测试：JSON 容错解析 + 评分条目提取"""


def test_parse_json_object_variants():
    from app.services.llm_judge import parse_json_object

    assert parse_json_object('{"match": 1}') == {"match": 1}
    assert parse_json_object('```json\n{"match": null}\n```') == {"match": None}
    assert parse_json_object('前置文字 {"match": 3} 后置') == {"match": 3}
    assert parse_json_object('{"clusters": [1, 2]}') == {"clusters": [1, 2]}
    assert parse_json_object("[1, 2]") is None  # 数组不是对象
    assert parse_json_object("垃圾") is None


def test_parse_json_list_variants():
    from app.services.llm_judge import parse_json_list

    assert parse_json_list('[{"id": 1}]') == [{"id": 1}]
    assert parse_json_list('```json\n[{"id": 2}]\n```') == [{"id": 2}]
    assert parse_json_list('前缀 [{"id": 3}] 后缀') == [{"id": 3}]
    assert parse_json_list('{"scores": [1]}') is None  # 对象不是数组
    assert parse_json_list("垃圾") is None


def test_parse_score_items_robust():
    from app.services.llm_judge import parse_score_items

    # 裸数组
    assert parse_score_items('[{"id": 1, "score": 5}, {"id": 2, "score": 3}]') == [
        {"id": 1, "score": 5},
        {"id": 2, "score": 3},
    ]
    # 对象包裹
    assert parse_score_items('{"scores": [{"id": 1, "score": 5}]}') == [
        {"id": 1, "score": 5}
    ]
    # 过滤非 dict 元素（mimo 偶发输出 "5分" 字符串）
    assert parse_score_items('[{"id": 1, "score": 5}, "5分"]') == [
        {"id": 1, "score": 5}
    ]
    # 碎片恢复：reason 含全角引号（部分模型输出风格）
    raw = '[{"id": 1, "score": 5, "reason": "考察「缓存」场景"}]'
    result = parse_score_items(raw)
    assert len(result) >= 1
    # 垃圾输入 → []
    assert parse_score_items("完全无关") == []

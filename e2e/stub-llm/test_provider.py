from provider import _match_exact_questions


def test_match_exact_questions_reuses_existing_canonical_and_reports_unmatched():
    prompt = """\
注意：【待匹配的新题目】是一个不超过 40 道题的微批次，请逐题判断。

【已有标准题库】（格式：[聚类ID] 代表题目）：
[77] [Agent协作] 多智能体系统如何设计任务协作？
[78] RAG 检索结果不相关时如何定位问题？

【待匹配的新题目】（微批次，共 2 题）：
[2] 多智能体系统如何设计任务协作？
[3] 一个新问题？

请输出 JSON 格式。
"""

    assert _match_exact_questions(prompt) == {
        "matches": [{"new_id": "2", "cluster_id": "77", "confidence": 0.99}],
        "unmatched": ["3"],
    }


def test_match_exact_questions_deduplicates_repeated_repair_prompt_ids():
    prompt = """\
【已有标准题库】
[77] 多智能体系统如何设计任务协作？
【待匹配的新题目】
[2] 多智能体系统如何设计任务协作？
[2] 多智能体系统如何设计任务协作？
请输出 JSON
"""

    assert _match_exact_questions(prompt) == {
        "matches": [{"new_id": "2", "cluster_id": "77", "confidence": 0.99}],
        "unmatched": [],
    }

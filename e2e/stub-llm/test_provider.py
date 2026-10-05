from provider import _match_exact_questions, _StubCallLedger


def test_stub_call_ledger_releases_only_the_requested_question_marker():
    ledger = _StubCallLedger(fail_markers={"AC011_QUESTION_09", "AC011_QUESTION_10"})

    assert ledger.record("AC011_QUESTION_09") is True
    assert ledger.record("AC011_QUESTION_10") is True
    assert ledger.record("AC011_QUESTION_08") is False
    assert ledger.counts() == {
        "AC011_QUESTION_09": 1,
        "AC011_QUESTION_10": 1,
        "AC011_QUESTION_08": 1,
    }

    ledger.release("AC011_QUESTION_09")
    assert ledger.record("AC011_QUESTION_09") is False
    assert ledger.record("AC011_QUESTION_10") is True


def test_stub_call_ledger_cross_checks_physical_http_status_by_synthetic_marker():
    ledger = _StubCallLedger(fail_markers={"AC013_RATE_429"})

    assert ledger.record("AC013_RATE_429") is True
    ledger.record_http_access()
    ledger.record_http_status(429, marker="AC013_RATE_429")
    ledger.release("AC013_RATE_429")
    assert ledger.record("AC013_RATE_429") is False
    ledger.record_http_access()
    ledger.record_http_status(200, marker="AC013_RATE_429")

    assert ledger.counts() == {"AC013_RATE_429": 2}
    assert ledger.access() == {
        "requests": 2,
        "statuses": {"429": 1, "200": 1},
        "marker_statuses": {"AC013_RATE_429": {"429": 1, "200": 1}},
    }


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

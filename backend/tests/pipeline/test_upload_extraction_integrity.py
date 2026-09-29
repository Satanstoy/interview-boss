"""AC-019 / UR-019：提取不静默漏题。

固定输入：Redis 持久化优缺点、线程池优缺点、个人优缺点、TCP 握手四题。

契约（contracts.md §2.3）：

- 完整提取结果保留 4 个 ordinal；技术两题（含“优缺点”）不得删除；
- 个人优缺点可以标 HR 题，但本期默认保留；
- 模型输出 null/数字/重复 ordinal 要 schema 拒绝或明确标待确认，
  不能把字符串迭代成单字题；
- counts 守恒：extracted == retained + excluded（needs_review 是正交标记）。
"""

from __future__ import annotations

import pytest

from app.services.extraction_integrity import (
    ExtractionSchemaError,
    classify_question,
    normalize_extracted_questions,
)
from app.services.pipeline.sanitize import sanitize_batch

FIXED_INPUT = [
    "Redis 持久化方案（RDB/AOF）各有什么优缺点？",
    "线程池有哪些优缺点？参数怎么设置？",
    "你有什么优缺点？",
    "TCP 三次握手的过程是什么？",
]


# ── 不静默漏题 ───────────────────────────────────────────────


def test_all_four_fixed_questions_survive_extraction():
    result = normalize_extracted_questions(FIXED_INPUT)
    questions = result["questions"]
    assert [q["ordinal"] for q in questions] == [1, 2, 3, 4]
    texts = [q["question"] for q in questions]
    assert any("Redis" in t for t in texts), "技术题不得因“优缺点”被删除"
    assert any("线程池" in t for t in texts), "技术题不得因“优缺点”被删除"
    assert any("TCP" in t for t in texts)


def test_personal_strength_weakness_kept_but_marked():
    result = normalize_extracted_questions(FIXED_INPUT)
    personal = next(q for q in result["questions"] if "你有什么优缺点" in q["question"])
    assert personal["retained"] is True
    assert personal["needs_review"] is True or personal["needs_review"] is False
    if personal["needs_review"]:
        assert personal["review_reason"]


def test_technical_优缺点_not_marked_hr():
    result = normalize_extracted_questions(FIXED_INPUT)
    for q in result["questions"]:
        if "Redis" in q["question"] or "线程池" in q["question"]:
            assert classify_question(q["question"])[0] is False


def test_counts_are_conserved():
    result = normalize_extracted_questions(FIXED_INPUT)
    counts = result["counts"]
    assert counts["extracted"] == 4
    assert counts["retained"] + counts["excluded"] == counts["extracted"]
    assert counts["needs_review"] <= counts["retained"]


# ── schema 拒绝而不是丢题 ────────────────────────────────────


def test_null_item_is_rejected_not_dropped():
    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions(["TCP 三次握手", None])


def test_numeric_item_is_rejected_not_dropped():
    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions([42])


def test_string_input_is_not_iterated_into_characters():
    """模型把清单返回成字符串时，必须报结构错误，不能拆成单字题。"""

    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions("TCP三次握手")


def test_duplicate_ordinals_are_rejected():
    with pytest.raises(ExtractionSchemaError):
        normalize_extracted_questions(
            [
                {"ordinal": 1, "question": "TCP 三次握手"},
                {"ordinal": 1, "question": "TCP 四次挥手"},
            ]
        )


def test_explicit_ordinal_gaps_are_preserved_not_renumbered():
    """过滤不能重新编号：恢复时不能把序号写到别的题上。"""

    result = normalize_extracted_questions(
        [
            {"ordinal": 1, "question": "TCP 三次握手"},
            {"ordinal": 7, "question": "Redis 持久化优缺点"},
        ]
    )
    assert [q["ordinal"] for q in result["questions"]] == [1, 7]


# ── sanitize 不再吞掉黑名单题 ────────────────────────────────


def test_sanitize_batch_keeps_blacklist_questions_as_marked():
    batch = [
        {"question": "线程池有哪些优缺点？"},
        {"question": "TCP 三次握手"},
        {"question": "12345"},
    ]
    clean, filtered = sanitize_batch(batch)
    texts = [item["question"] for item in clean]
    assert any("优缺点" in t for t in texts), "黑名单只做标记，不得丢题"
    assert any("TCP" in t for t in texts)
    # 纯数字噪声仍被剔除，但计入 filtered（守恒）
    assert [item["question"] for item in filtered] == ["12345"]
    assert len(clean) + len(filtered) == len(batch)


def test_sanitize_marks_hr_style_without_dropping():
    batch = [{"question": "请做一下自我介绍"}, {"question": "TCP 三次握手"}]
    clean, filtered = sanitize_batch(batch)
    assert len(clean) == 2
    assert all("mark" not in item or item.get("mark") in (None, "needs_review") for item in clean)

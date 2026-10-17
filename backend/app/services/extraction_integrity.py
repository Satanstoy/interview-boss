"""提取结果完整性（AC-019 / UR-019）：不静默漏题、schema 校验、counts 守恒。

此前提取/清洗会用子串黑名单（含“优缺点”）直接丢题，把
“Redis 持久化有哪些优缺点”这类技术题一起删掉，且没有任何记录。
现在：

- 结构错误（null/数字/字符串当数组/重复 ordinal）抛 ``ExtractionSchemaError``，
  视为 ``MODEL_OUTPUT_INVALID``，走有限修复重试，绝不当 no_match/丢题；
- HR 类表述只做 ``needs_review`` 标记，默认保留；
- ``counts`` 守恒：extracted == retained + excluded。
"""

from __future__ import annotations

from typing import Any

# 只标记、不删除：这些表述更像 HR 题，但仍可能包含有效考察点
HR_STYLE_PHRASES = (
    "自我介绍",
    "反问",
    "想问我",
    "职业规划",
    "加班",
    "薪资",
    "为什么离职",
)


class ExtractionSchemaError(ValueError):
    """模型输出结构不合法；禁止静默丢弃或拆字成题。"""

    code = "MODEL_OUTPUT_INVALID"
    retryable = True


def classify_question(question: str) -> tuple[bool, str | None]:
    """返回 ``(needs_review, reason)``。技术题（含“优缺点”）一律不标记。"""

    text = str(question or "")
    for phrase in HR_STYLE_PHRASES:
        if phrase in text:
            return True, f"含 HR 类表述「{phrase}」，建议人工确认"
    return False, None


def _as_int_ordinal(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExtractionSchemaError(f"ordinal 必须是整数，收到: {value!r}")
    return int(value)


def normalize_extracted_questions(raw: Any) -> dict:
    """把模型输出的题目清单规范化为稳定 ordinal 列表 + 守恒计数。"""

    if isinstance(raw, (str, bytes)):
        raise ExtractionSchemaError("题目清单必须是数组，不能把字符串拆成单字题")
    if not isinstance(raw, list):
        raise ExtractionSchemaError(f"题目清单必须是数组，收到: {type(raw).__name__}")

    questions: list[dict] = []
    seen_ordinals: set[int] = set()

    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            ordinal = _as_int_ordinal(item.get("ordinal", index))
            text = item.get("question")
        else:
            ordinal = index
            text = item

        if not isinstance(text, str) or not text.strip():
            raise ExtractionSchemaError(f"第 {index} 项不是非空字符串: {text!r}")
        if ordinal in seen_ordinals:
            raise ExtractionSchemaError(f"重复的题目 ordinal: {ordinal}")
        seen_ordinals.add(ordinal)

        needs_review, reason = classify_question(text)
        questions.append(
            {
                "ordinal": ordinal,
                "question": text.strip(),
                "retained": True,
                "needs_review": needs_review,
                "review_reason": reason,
            }
        )

    questions.sort(key=lambda q: q["ordinal"])
    retained = sum(1 for q in questions if q["retained"])
    excluded = sum(1 for q in questions if not q["retained"])
    return {
        "questions": questions,
        "counts": {
            "extracted": len(questions),
            "retained": retained,
            "excluded": excluded,
            "needs_review": sum(1 for q in questions if q["needs_review"]),
        },
    }

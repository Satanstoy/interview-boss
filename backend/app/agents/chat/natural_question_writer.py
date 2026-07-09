"""NaturalQuestionWriter: 将 question_intent 改写为自然面试官问题。"""

from __future__ import annotations

import re
from typing import Any, Callable, Awaitable

from app.agents.chat.prompts import NATURAL_QUESTION_WRITER_PROMPT


class GenerationError(Exception):
    """自然问题生成失败。"""
    def __init__(self, code: str, message: str, guard: str | None = None):
        self.code = code
        self.message = message
        self.guard = guard
        super().__init__(message)


# 机械复述检测：以"好，"开头 + 直接跟题干
_MECHANICAL_PATTERNS = (
    re.compile(r"^好[，,]\s*.{0,50}[？?。.]?$"),  # "好，XXX？" 短句
    re.compile(r"^[请]?.{0,5}(回答|解释|说明|描述)一下"),  # "请回答一下"
)


async def generate_natural_question(
    *,
    question_intent: dict[str, Any],
    selected_question: dict[str, Any] | None,
    context_anchor: str,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> dict[str, Any]:
    """生成自然化面试问题。

    Returns:
        {"status": "success", "text": "..."} 或
        {"status": "error", "error_code": "...", "message": "...", "guard": "..."}
    """
    question_text = (selected_question or {}).get("question") or question_intent.get("question", "")
    question_type = question_intent.get("question_type", "new_question")

    # 构建 prompt
    system_prompt = NATURAL_QUESTION_WRITER_PROMPT
    user_content = f"""## 待自然化的问题
- 原始题干: {question_text}
- 题型: {question_type}
- 上下文锚点: {context_anchor}
- transition_style: {question_intent.get('transition_style', 'natural')}

请将上述问题改写为自然的面试官口吻。直接输出面试官可以说的话，不要加任何前缀或解释。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        raw = await llm_call(messages)
    except Exception as exc:
        return {
            "status": "error",
            "error_code": "natural_question_generation_failed",
            "message": f"LLM 调用失败: {exc}",
            "guard": None,
        }

    text = (raw or "").strip()

    # Guard 1: 空输出
    if not text:
        return {
            "status": "error",
            "error_code": "natural_question_generation_failed",
            "message": "LLM 输出为空",
            "guard": "naturalness",
        }

    # Guard 2: 机械复述
    if _is_mechanical(text, question_text):
        return {
            "status": "error",
            "error_code": "natural_question_generation_failed",
            "message": f"输出为机械复述: {text[:50]}",
            "guard": "naturalness",
        }

    # Guard 3: 目标对齐（检查是否保留了评估目标）
    if selected_question and not _preserves_evaluation_goal(text, question_text):
        return {
            "status": "error",
            "error_code": "natural_question_generation_failed",
            "message": "输出偏离评估目标",
            "guard": "target_question_alignment",
        }

    return {"status": "success", "text": text}


def _is_mechanical(text: str, original_question: str) -> bool:
    """检测是否为机械复述。"""
    # 检查是否以"好，"开头且内容过短
    for pattern in _MECHANICAL_PATTERNS:
        if pattern.match(text):
            return True

    # 检查是否只是题干的简单重述
    if text.replace("？", "").replace("?", "").strip() == original_question.replace("？", "").replace("?", "").strip():
        return True

    return False


def _preserves_evaluation_goal(text: str, original_question: str) -> bool:
    """检查是否保留了评估目标。"""
    # 提取原始问题中的技术关键词
    original_keywords = set()
    # 提取英文词
    original_keywords.update(re.findall(r'[a-zA-Z]+', original_question))
    # 提取2-3字的中文词
    chinese_chars = re.findall(r'[一-鿿]+', original_question)
    for segment in chinese_chars:
        for length in (2, 3):
            for i in range(len(segment) - length + 1):
                original_keywords.add(segment[i:i+length])

    if not original_keywords:
        return True

    # 检查每个原始关键词是否作为子串出现在生成文本中
    matched = sum(1 for kw in original_keywords if kw in text)
    overlap = matched / len(original_keywords)
    return overlap >= 0.3

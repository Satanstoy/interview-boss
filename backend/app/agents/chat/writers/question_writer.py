"""QuestionWriter — 生成自然面试问题并验证语义一致性。

当 TurnContract.action == "ask_selected_question" 时：
1. 使用 LLM 将 selected_question 改写为自然面试官口吻
2. 使用 semantic_question_adherence validator 验证语义一致性
3. 失败后带 feedback 重试一次
4. 仍失败则返回 GenerationError

这是对现有 natural_question_writer.py 的升级版，集成了验证流程。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

logger = logging.getLogger("interview-boss")

# 机械复述检测
_MECHANICAL_PATTERNS = (
    re.compile(r"^好[，,]\s*.{0,50}[？?。.]?$"),
    re.compile(r"^[请]?.{0,5}(回答|解释|说明|描述)一下"),
)


def _build_question_writer_prompt(
    *,
    selected_question: dict[str, Any],
    context_anchor: str,
    question_type: str,
) -> str:
    """构建 question writer 的用户 prompt。"""
    question_text = selected_question.get("question", "")
    return (
        f"## 待自然化的问题\n"
        f"- 原始题干: {question_text}\n"
        f"- 题型: {question_type}\n"
        f"- 上下文锚点: {context_anchor}\n\n"
        "请将上述问题改写为自然的面试官口吻。直接输出面试官可以说的话，不要加任何前缀或解释。"
    )


def _is_mechanical(text: str, original_question: str) -> bool:
    """检测是否为机械复述。"""
    for pattern in _MECHANICAL_PATTERNS:
        if pattern.match(text):
            return True
    # 检查是否只是题干的简单重述
    cleaned_text = text.replace("？", "").replace("?", "").strip()
    cleaned_original = original_question.replace("？", "").replace("?", "").strip()
    if cleaned_text == cleaned_original:
        return True
    return False


async def generate_question_with_validation(
    *,
    selected_question: dict[str, Any],
    context_anchor: str,
    question_type: str,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
    validator: Callable[..., Awaitable[dict[str, Any]]],
    max_retries: int = 1,
) -> dict[str, Any]:
    """生成自然面试问题并验证语义一致性。

    Args:
        selected_question: 计划问的问题 {"id": ..., "question": ...}
        context_anchor: 上下文锚点（上一题的回答内容）
        question_type: 题型
        llm_call: LLM 调用函数
        validator: semantic_question_adherence validator
        max_retries: 最大重试次数（默认 1）

    Returns:
        {"status": "success", "text": "...", "validator_result": {...}} 或
        {"status": "error", "error_code": "...", "message": "..."}
    """
    question_text = selected_question.get("question", "")
    system_prompt = (
        "你是面试官，需要将给定的问题改写为自然的面试官口吻。\n\n"
        "要求：\n"
        "- 直接输出面试官可以说的话\n"
        "- 不要加任何前缀或解释\n"
        "- 保持问题的核心评估目标不变\n"
        "- 使用自然的过渡语，不要机械复述题干\n"
    )

    user_prompt = _build_question_writer_prompt(
        selected_question=selected_question,
        context_anchor=context_anchor,
        question_type=question_type,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_validator_result = None

    for attempt in range(max_retries + 1):
        # 生成
        try:
            raw = await llm_call(messages)
        except Exception as exc:
            logger.warning("Question writer LLM call failed (attempt %d): %s", attempt + 1, exc)
            return {
                "status": "error",
                "error_code": "question_generation_failed",
                "message": f"LLM 调用失败: {exc}",
            }

        text = (raw or "").strip()

        # Guard: 空输出
        if not text:
            return {
                "status": "error",
                "error_code": "question_generation_failed",
                "message": "LLM 输出为空",
            }

        # Guard: 机械复述
        if _is_mechanical(text, question_text):
            logger.warning("Question writer: mechanical output detected (attempt %d)", attempt + 1)
            if attempt < max_retries:
                # 带 feedback 重试
                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"{user_prompt}\n\n"
                            "注意：你之前的输出被检测为机械复述，请用更自然的方式改写。"
                        ),
                    },
                ]
                continue
            return {
                "status": "error",
                "error_code": "question_mechanical",
                "message": f"输出为机械复述: {text[:50]}",
            }

        # 验证
        validator_result = await validator(
            generated_text=text,
            selected_question=selected_question,
            llm_call=llm_call,
        )
        last_validator_result = validator_result

        if validator_result.get("passes"):
            return {
                "status": "success",
                "text": text,
                "validator_result": validator_result,
                "retry_count": attempt,
            }

        # 验证失败
        logger.warning(
            "Question writer: validation failed (attempt %d): score=%.2f reason=%s",
            attempt + 1,
            validator_result.get("score", 0),
            validator_result.get("reason", ""),
        )

        if attempt < max_retries:
            # 带 validator feedback 重试
            feedback = validator_result.get("reason", "验证失败")
            issues = validator_result.get("issues", [])
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{user_prompt}\n\n"
                        f"注意：你之前的输出验证失败。\n"
                        f"- 原因: {feedback}\n"
                        f"- 问题: {', '.join(issues)}\n"
                        f"请重新生成，确保问题与原始题干语义一致。"
                    ),
                },
            ]
            continue

    # 所有重试都失败
    return {
        "status": "error",
        "error_code": "question_validation_failed",
        "message": f"验证失败: {last_validator_result.get('reason', 'unknown')}",
        "validator_result": last_validator_result,
    }

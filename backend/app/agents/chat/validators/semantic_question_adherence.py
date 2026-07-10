"""Semantic Question Adherence Validator — 验证生成问题是否语义一致。

当 TurnContract.action == "ask_selected_question" 时，此 validator 检查最终生成的
用户可见文本是否真的在问 selected_question 的问题，而不是偏离到其他话题。

失败后带 feedback 重试一次；仍失败则返回 GenerationError。
阈值：passes=true 且 score >= 0.75。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable

logger = logging.getLogger("interview-boss")

# 阈值：passes=true 且 score >= 0.75
_PASS_THRESHOLD = 0.75

_VALIDATOR_PROMPT = (
    "你是一个面试问题一致性验证器。\n\n"
    "任务：检查面试官最终生成的问题是否与计划问的问题语义一致。\n\n"
    "输入：\n"
    "- selected_question: 计划问的问题\n"
    "- generated_text: 面试官最终生成的用户可见文本\n\n"
    "判断标准：\n"
    "- 最终文本是否在问 selected_question 的核心问题\n"
    "- 允许自然改写、添加上下文、调整措辞\n"
    "- 不允许完全偏离到其他话题\n\n"
    "请严格以 JSON 格式输出：\n"
    "{\n"
    '  "passes": true/false,\n'
    '  "score": 0.0-1.0,\n'
    '  "reason": "简短说明",\n'
    '  "detected_question": "从生成文本中检测到的实际问题",\n'
    '  "issues": ["可选：问题列表，如 topic_drift, missing_key_concept 等"]\n'
    "}\n"
    "不要包含任何其他文字，只输出纯 JSON。"
)


def _extract_detected_question(text: str) -> str:
    """从生成文本中提取检测到的问题。

    尝试找到以问号结尾的句子；如果没有，返回文本的最后部分。
    """
    # 找到以问号结尾的句子
    sentences = re.split(r"[。！？!?]", text)
    for sentence in reversed(sentences):
        stripped = sentence.strip()
        if stripped and len(stripped) > 5:
            return stripped
    # 没有找到问句，返回文本末尾
    return text[-100:].strip() if len(text) > 100 else text.strip()


async def validate_question_adherence(
    *,
    generated_text: str,
    selected_question: dict[str, Any],
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> dict[str, Any]:
    """验证生成问题是否与 selected_question 语义一致。

    Args:
        generated_text: 面试官最终生成的用户可见文本
        selected_question: 计划问的问题 {"id": ..., "question": ...}
        llm_call: LLM 调用函数

    Returns:
        {
            "passes": bool,
            "score": float,
            "reason": str,
            "detected_question": str,
            "issues": list[str],
        }
    """
    question_text = selected_question.get("question", "")
    question_id = selected_question.get("id", "unknown")

    user_content = (
        f"## 计划问的问题 (ID: {question_id})\n{question_text}\n\n"
        f"## 面试官最终生成的文本\n{generated_text}\n\n"
        "请判断最终文本是否在问计划题的核心问题。"
    )

    messages = [
        {"role": "system", "content": _VALIDATOR_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        raw = await llm_call(messages)
    except Exception as exc:
        logger.warning("semantic_question_adherence LLM call failed: %s", exc)
        return {
            "passes": False,
            "score": 0.0,
            "reason": f"LLM 调用失败: {exc}",
            "detected_question": _extract_detected_question(generated_text),
            "issues": ["llm_call_error"],
        }

    # 解析 JSON
    try:
        # 尝试提取 JSON
        json_match = re.search(r"```json\s*(.*?)\s```", raw, re.DOTALL)
        json_str = json_match.group(1) if json_match else raw
        if not json_match:
            obj_match = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = obj_match.group(0) if obj_match else raw

        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        logger.warning("semantic_question_adherence: invalid JSON response: %s", raw[:100])
        return {
            "passes": False,
            "score": 0.0,
            "reason": f"JSON 解析失败: {raw[:100]}",
            "detected_question": _extract_detected_question(generated_text),
            "issues": ["json_parse_error"],
        }

    # 应用阈值
    score = float(data.get("score", 0.0))
    passes = bool(data.get("passes", False)) and score >= _PASS_THRESHOLD

    return {
        "passes": passes,
        "score": score,
        "reason": data.get("reason", ""),
        "detected_question": data.get("detected_question", _extract_detected_question(generated_text)),
        "issues": data.get("issues", []),
    }

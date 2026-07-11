"""ClarifyWriter — 围绕候选人当前回答补充证据，不引入新题。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


async def generate_clarification(
    *,
    candidate_answer: str,
    recent_context: str,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是技术面试官。候选人的当前回答需要补充证据。"
                "只围绕这段回答提出一个自然、具体的澄清问题，"
                "不要切换到新技术主题，不要输出总结、评分或解释。"
            ),
        },
        {
            "role": "user",
            "content": f"最近上下文：\n{recent_context}\n\n候选人当前回答：\n{candidate_answer}",
        },
    ]
    try:
        text = (await llm_call(messages) or "").strip()
    except Exception as exc:
        return {"status": "error", "error_code": "clarification_generation_failed", "message": f"LLM 调用失败: {exc}"}
    if not text:
        return {"status": "error", "error_code": "clarification_generation_failed", "message": "LLM 输出为空"}
    return {"status": "success", "text": text}

"""CounterWriter — 回答候选人的反问，不延续技术追问。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


async def generate_counter_answer(
    *,
    candidate_question: str,
    topic: str | None,
    recent_context: str,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是技术面试官，正在回答候选人的反问。"
                "基于已有上下文如实、简洁地回答；不确定的信息要说明无法确认。"
                "不要编造团队、岗位或业务事实，不要在结尾追加新的技术面试题。"
            ),
        },
        {
            "role": "user",
            "content": f"反问主题：{topic or '未归类'}\n候选人问题：{candidate_question}\n\n最近上下文：\n{recent_context}",
        },
    ]
    try:
        text = (await llm_call(messages) or "").strip()
    except Exception as exc:
        return {"status": "error", "error_code": "counter_answer_generation_failed", "message": f"LLM 调用失败: {exc}"}
    if not text:
        return {"status": "error", "error_code": "counter_answer_generation_failed", "message": "LLM 输出为空"}
    return {"status": "success", "text": text}

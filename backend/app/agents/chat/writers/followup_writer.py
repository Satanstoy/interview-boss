"""FollowupWriter — 基于已知评估焦点生成自然追问。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


async def generate_followup(
    *,
    candidate_answer: str,
    next_focus: str,
    recent_context: str,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是技术面试官。根据候选人刚才的回答和当前评估焦点，"
                "提出一个自然的后续问题。一次只问一个问题，"
                "不要输出面试总结、评分、内部流程或机械题干。"
                "当前评估焦点若为 candidate_question，必须自然邀请候选人提出反问，"
                "不能再问技术题。"
            ),
        },
        {
            "role": "user",
            "content": f"当前评估焦点：{next_focus or '项目细节'}\n候选人回答：{candidate_answer}\n\n最近上下文：\n{recent_context}",
        },
    ]
    try:
        text = (await llm_call(messages) or "").strip()
    except Exception as exc:
        return {"status": "error", "error_code": "followup_generation_failed", "message": f"LLM 调用失败: {exc}"}
    if not text:
        return {"status": "error", "error_code": "followup_generation_failed", "message": "LLM 输出为空"}
    return {"status": "success", "text": text}

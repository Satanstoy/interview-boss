"""ClosingWriter — 生成自然收尾语。

职责：生成面试结束时的自然收尾语，不包含结构化总结。
收尾语由 closing_writer 生成，结构化总结由 summary_writer 生成。
两阶段输出：closing_utterance + summary。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("interview-boss")

# 收尾语不应包含的总结信号
_SUMMARY_SIGNALS = (
    "面试总结",
    "整体表现",
    "综合评分",
    "综合评价",
    "技术主题",
    "最佳话题",
    "薄弱环节",
    "改进建议",
    "hiring signal",
    "风险点",
    "下一轮追问",
    "评分",
    "得分",
)

# 机械收尾模式（太短或太模板化）
_BARE_GOODBYE_PATTERNS = (
    "今天先到这里",
    "再见",
    "感谢参加",
    "面试结束",
    "到这里吧",
    "先这样",
    "就到这里",
    "拜拜",
)


def _is_bare_goodbye(text: str) -> bool:
    """检测是否为过于简短的机械收尾。

    只有当文本几乎完全由告别语组成时才判定为 bare goodbye。
    包含告别语但有其他实质内容的不算。
    """
    stripped = text.strip()
    if not stripped:
        return False  # 空文本由其他 guard 处理
    # 去除标点和空白后，检查是否完全由告别语组成
    import re
    cleaned = re.sub(r"[，。！？、\s]", "", stripped)
    if not cleaned:
        return False
    # 逐个尝试从 cleaned 中去除告别模式，看剩余是否为空或只有语气词
    remaining = cleaned
    for pattern in _BARE_GOODBYE_PATTERNS:
        cleaned_pattern = re.sub(r"[，。！？、\s]", "", pattern)
        remaining = remaining.replace(cleaned_pattern, "")
    # 去除所有告别模式后，剩余为空或只有语气词/连接词
    return remaining in ("", "好", "吧", "啦", "呢", "就", "先")


def _contains_summary_content(text: str) -> bool:
    """检测是否包含结构化总结内容。"""
    return any(signal in text for signal in _SUMMARY_SIGNALS)


_CLOSING_SYSTEM_PROMPT = (
    "你是面试官，正在结束一轮模拟面试。\n\n"
    "要求：\n"
    "- 说一句自然的收尾语，像真实面试官结束面试时会说的话\n"
    "- 语气友好、专业、简洁\n"
    "- 不要包含任何总结、评价、评分或反馈内容（那些会单独生成）\n"
    "- 不要使用过于模板化的告别语（如'再见'、'面试结束'）\n"
    "- 直接输出面试官可以说的话，不要加任何前缀或解释\n"
)


async def generate_closing_utterance(
    *,
    closing_reason: str,
    recent_context: str,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> dict[str, Any]:
    """生成自然收尾语。

    Args:
        closing_reason: 收尾原因（如 coverage_complete、hard_stop_by_message_count）
        recent_context: 最近的面试上下文
        llm_call: LLM 调用函数

    Returns:
        {"status": "success", "text": "..."} 或
        {"status": "error", "error_code": "...", "message": "..."}
    """
    user_content = (
        f"## 收尾原因\n{closing_reason}\n\n"
        f"## 最近面试上下文\n{recent_context}\n\n"
        "请生成一句自然的面试收尾语。不要包含任何总结或评价内容。"
    )

    messages = [
        {"role": "system", "content": _CLOSING_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        raw = await llm_call(messages)
    except Exception as exc:
        return {
            "status": "error",
            "error_code": "closing_generation_failed",
            "message": f"LLM 调用失败: {exc}",
        }

    text = (raw or "").strip()

    # Guard 1: 空输出
    if not text:
        return {
            "status": "error",
            "error_code": "closing_generation_failed",
            "message": "LLM 输出为空",
        }

    # Guard 2: 包含总结内容
    if _contains_summary_content(text):
        return {
            "status": "error",
            "error_code": "closing_contains_summary",
            "message": f"收尾语包含总结内容: {text[:80]}",
        }

    # Guard 3: 过于机械的收尾
    if _is_bare_goodbye(text):
        return {
            "status": "error",
            "error_code": "closing_too_bare",
            "message": f"收尾语过于简短: {text[:50]}",
        }

    return {"status": "success", "text": text}

"""Interview ending and summary generation.

Split from pipeline.py — contains structured summary generation,
interview closing responses, and error sanitization.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel

from app.agents.chat.state import ChatState
from app.services.llm import _call_llm_with_retry_messages, _extract_json

logger = logging.getLogger("interview-boss")

_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"


class InterviewSummary(BaseModel):
    """LLM-generated structured interview feedback."""

    overall_comment: str  # 2-3 sentences, based on actual dialogue
    strongest_topic: str  # Best performed topic + specific reason
    weakest_topic: str  # Weakest topic + specific evidence
    key_suggestions: list[str]  # 3 actionable suggestions
    score_estimate: int  # 1-10 overall estimate


_SUMMARY_SYSTEM_PROMPT = (
    '你是一个面试复盘教练。基于以下面试记录，给出一份结构化的面试反馈。\n\n'
    '要求：\n'
    '- 评价必须基于候选人实际说了什么，不要用泛泛的套话\n'
    '- 最弱的话题要给出具体的"答不上来"或"答得浅"的证据\n'
    '- 建议要具体可操作（如"建议复习 LangGraph 的条件路由机制"），'
    '不要给空泛建议（如"继续深度学习"）\n'
    '- 整体评价要诚实，好的夸、差的指出\n\n'
    '请严格以 JSON 格式输出，schema 如下：\n'
    '{\n'
    '  "overall_comment": "2-3句整体评价",\n'
    '  "strongest_topic": "表现最好的话题及原因",\n'
    '  "weakest_topic": "最薄弱的话题及具体证据",\n'
    '  "key_suggestions": ["具体建议1", "具体建议2", "具体建议3"],\n'
    '  "score_estimate": 7\n'
    '}\n'
    '不要包含任何其他文字或 markdown 代码块，只输出纯 JSON。'
)


def _build_interview_transcript(state: ChatState) -> str:
    """Extract the interview transcript from state for the summary prompt."""
    history = state.get("message_history", []) or []
    # Take the last 20 messages (or all if shorter)
    recent = history[-20:] if len(history) > 20 else history
    lines: list[str] = []
    for msg in recent:
        role = "面试官" if msg.get("role") == "assistant" else "候选人"
        content = str(msg.get("content") or "")
        if content.strip():
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _render_interview_summary_markdown(summary: InterviewSummary) -> str:
    """Render an InterviewSummary as user-facing markdown."""
    suggestions = "\n".join(f"- {s}" for s in summary.key_suggestions)
    return (
        "今天的模拟面试就到这里，感谢你的时间。\n\n"
        f"**整体表现**：{summary.overall_comment}\n\n"
        f"**最佳话题**：{summary.strongest_topic}\n\n"
        f"**薄弱环节**：{summary.weakest_topic}\n\n"
        f"**改进建议**：\n{suggestions}\n\n"
        f"**综合评分**：{summary.score_estimate}/10"
    )


async def _generate_structured_summary(state: ChatState) -> str:
    """Call LLM to generate structured interview feedback.

    Falls back to an improved generic summary if LLM call fails.
    """
    transcript = _build_interview_transcript(state)
    history = state.get("message_history", []) or []
    session_notes = state.get("session_notes", "") or ""

    # Build prompt even if transcript is empty (use message count + session notes)
    transcript_section = transcript if transcript.strip() else "（对话记录内容较少）"

    user_content = (
        "以下是面试记录：\n\n"
        f"{transcript_section}\n\n"
        f"面试官备注：{session_notes}\n"
        f"总对话轮数：{len(history)}"
    )

    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        raw = await _call_llm_with_retry_messages(
            messages,
            user_id=state.get("user_id"),
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = _extract_json(raw)
        summary = InterviewSummary(**data)
        return _render_interview_summary_markdown(summary)
    except Exception as e:
        logger.warning(
            "Interview summary LLM call failed, using fallback: %s", e
        )
        # Improved fallback: at least mention topic count from session notes
        topic_count = len(re.findall(r"\[asked\]", session_notes))
        topic_info = f"共覆盖了 {topic_count} 个话题" if topic_count else "覆盖了多个话题"
        return (
            "今天的模拟面试就到这里，感谢你的时间。\n\n"
            f"**整体表现**：本次面试{topic_info}，"
            "你在项目经验和基础知识方面都有一定积累，回答思路基本清晰。"
            "建议后续重点复盘面试中暴露的知识盲区，"
            "尤其是回答不够深入的部分，可以结合实际项目多做总结。\n\n"
            "建议继续保持对核心技术的深度学习，祝后续面试顺利。"
        )


async def _forced_closing_response(state: ChatState) -> str:
    """Hard-stop overlong interviews so ReAct cannot drift back to tech rounds.

    Now generates a structured LLM-based summary instead of hardcoded text.
    """
    from app.agents.chat.answer import _last_assistant_message, _looks_like_candidate_question

    message_count = len(state.get("message_history", []) or [])
    if message_count <= 44:
        return ""

    state["question_source"] = "conversation"
    state["question_source_reason"] = "forced_closing_by_message_count"

    last_assistant = _last_assistant_message(state)
    user_message = state.get("user_message", "")
    if "你有什么想问" in last_assistant or _looks_like_candidate_question(user_message):
        # Candidate asked a counter-question; give a brief answer then the summary
        summary = await _generate_structured_summary(state)
        return (
            "这个问题简单回应一下：真实业务里的 Agent 落地，团队通常最看重稳定性和可评估性，"
            "工具调用、权限边界、状态管理和业务系统集成都要能闭环。实习生一般会从一个可控模块切入，"
            "比如评测体系、badcase 分析、某个工具接入或一条业务链路优化。\n\n"
            f"{summary}"
        )

    return await _generate_structured_summary(state)


async def _generate_end_interview_response(state: ChatState) -> str:
    """Generate a closing response when the user explicitly requests end_interview.

    This function is called when intent == 'end_interview'.  It MUST NOT call
    any tools (load_skill / search_questions / draw_questions).  It produces
    either a brief farewell or a structured LLM-generated summary depending
    on message count and whether the user explicitly requested a summary.

    Side-effects on *state*:
    - Sets question_source / question_source_reason for metadata.
    - Sets question_source to 'conversation' so downstream doesn't expect a
      selected_question binding.
    """
    state["question_source"] = "conversation"
    state["question_source_reason"] = "end_interview_hard_route"

    message_history = state.get("message_history", []) or []
    user_message = state.get("user_message", "")

    # If the user explicitly asks for a summary or the interview is substantial,
    # generate a structured LLM-based summary
    wants_summary = any(
        kw in user_message
        for kw in ("总结", "总结报告", "面试总结", "生成总结", "生成一份")
    )

    if wants_summary or len(message_history) >= 20:
        return await _generate_structured_summary(state)

    return "好的，面试先到这里。感谢你的时间，后续可以根据面试中暴露的问题继续针对性复盘。祝顺利！"


def _sanitize_error_message(e: Exception) -> str:
    err_str = str(e).lower()
    if "401" in err_str or "invalid api key" in err_str or "unauthorized" in err_str:
        return _FRIENDLY_ERROR
    return f"处理消息时出现错误: {str(e)}"

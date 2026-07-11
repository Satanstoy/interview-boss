"""Interview ending and summary generation.

Split from pipeline.py — contains structured summary generation,
interview closing responses, and error sanitization.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from app.agents.chat.state import ChatState
from app.agents.chat.decision_config import DecisionConfig
from app.services import llm as llm_service
from app.services.llm import _extract_json

logger = logging.getLogger("interview-boss")

_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"


class InterviewSummary(BaseModel):
    """Evidence-bound feedback for a simulated interview practice session."""

    overall_comment: str
    observed_strengths: list[str] = Field(default_factory=list)
    not_assessed: list[str] = Field(default_factory=list)
    key_suggestions: list[str] = Field(default_factory=list)
    coverage_note: str


_SUMMARY_SYSTEM_PROMPT = (
    "你是一个模拟面试复盘教练。基于以下面试记录，给出一份结构化的练习反馈。\n\n"
    "要求：\n"
    "- 只能陈述候选人实际说过的内容和本轮实际覆盖到的主题，不要补全不存在的表现\n"
    "- 某个问题没有回答、只说到一半或被候选人反问打断时，写入 not_assessed，绝不能推断为回避、薄弱或风险\n"
    "- 不输出招聘结论、是否进入下一轮、风险标签、综合评分或下一轮淘汰建议；这是练习反馈，不是招聘决策\n"
    '- 建议要具体可操作（如"建议复习 LangGraph 的条件路由机制"），'
    '不要给空泛建议（如"继续深度学习"）\n'
    "- overall_comment 必须说明证据范围，不足时直接说明本轮样本有限\n\n"
    "请严格以 JSON 格式输出，schema 如下：\n"
    "{\n"
    '  "overall_comment": "基于本轮证据的整体观察",\n'
    '  "observed_strengths": ["已观察到的具体表现和证据"],\n'
    '  "not_assessed": ["尚未充分覆盖或未作答的主题"],\n'
    '  "key_suggestions": ["具体建议1", "具体建议2", "具体建议3"],\n'
    '  "coverage_note": "本轮已覆盖和未覆盖范围的说明"\n'
    "}\n"
    "不要包含任何其他文字或 markdown 代码块，只输出纯 JSON。"
)


_SUMMARY_REQUEST_KEYWORDS = (
    "总结",
    "总结报告",
    "面试总结",
    "生成总结",
    "生成一份",
    "评价",
    "评估",
    "反馈",
    "复盘",
    "结论",
    "完整评价",
    "hiring signal",
    "hire signal",
    "强项",
    "风险",
    "薄弱",
    "不足",
    "证据不足",
    "高级工程师标准",
    "改进",
    "下一轮",
    "追问",
    "压测",
    "是否值得",
    "进入下一轮",
)

_PREMATURE_SUMMARY_GUARD_MESSAGE_COUNT = 6
_ABRUPT_EARLY_CLOSE_KEYWORDS = (
    "先别问",
    "别问了",
    "现在就结束",
    "现在结束",
    "直接给我",
    "是否通过",
    "通过与否",
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
    """Render an InterviewSummary as user-facing markdown.

    Phase 2: 不再内置固定收尾句。收尾语由 closing_writer 单独生成。
    """
    strengths = "\n".join(f"- {item}" for item in summary.observed_strengths) or "- 本轮尚未积累足够的可确认亮点。"
    not_assessed = "\n".join(f"- {item}" for item in summary.not_assessed) or "- 无。"
    suggestions = "\n".join(f"- {s}" for s in summary.key_suggestions) or "- 建议下一次围绕一个完整项目补充架构、取舍和结果。"
    sections = [
        f"**整体表现**：{summary.overall_comment}\n\n"
        f"**已观察到的表现**：\n{strengths}\n\n"
        f"**尚未充分评估**：\n{not_assessed}\n\n"
        f"**改进建议**：\n{suggestions}\n\n",
        f"**覆盖说明**：{summary.coverage_note}",
    ]
    return "".join(sections)


def _wants_structured_summary(user_message: str) -> bool:
    """Return True when the closing request asks for evaluation, not just goodbye."""
    normalized = user_message.lower()
    return any(keyword in normalized for keyword in _SUMMARY_REQUEST_KEYWORDS)


def _is_abrupt_premature_summary_request(
    user_message: str,
    message_history: list[dict],
) -> bool:
    """Return True for early pass/fail requests that should keep interviewing."""
    if len(message_history) >= _PREMATURE_SUMMARY_GUARD_MESSAGE_COUNT:
        return False
    normalized = user_message.lower()
    return any(keyword in normalized for keyword in _ABRUPT_EARLY_CLOSE_KEYWORDS)


def _last_assistant_prompt(message_history: list[dict]) -> str:
    for msg in reversed(message_history):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "").strip()
        if content:
            return content
    return ""


def _premature_summary_guard_response(state: ChatState) -> str:
    history = state.get("message_history", []) or []
    last_prompt = _last_assistant_prompt(history)
    state["question_source"] = "conversation"
    state["question_source_reason"] = "end_interview_premature_summary_guard"
    if last_prompt:
        return (
            "现在证据还不够，我不能基于这么少的信息给你“是否通过”的结论。"
            "我们先继续把关键证据补齐："
            f"{last_prompt}"
        )
    return (
        "现在证据还不够，我不能基于这么少的信息给你“是否通过”的结论。"
        "我们先继续面试：请你选一个最能代表你水平的项目，讲清楚背景、架构、你的职责和关键取舍。"
    )


async def _generate_structured_summary(
    state: ChatState,
    *,
    allow_fallback: bool = True,
) -> str:
    """Call LLM to generate structured interview feedback.

    Falls back to an improved generic summary only for legacy callers.
    The close_with_summary contract sets ``allow_fallback=False`` so a failed
    LLM summary never becomes a fabricated interview conclusion.
    """
    transcript = _build_interview_transcript(state)
    history = state.get("message_history", []) or []
    session_notes = state.get("session_notes", "") or ""

    # Build prompt even if transcript is empty (use message count + session notes)
    transcript_section = transcript if transcript.strip() else "（对话记录内容较少）"

    user_content = (
        "以下是面试记录：\n\n"
        f"{transcript_section}\n\n"
        f"候选人结束请求：{state.get('user_message', '')}\n"
        f"面试官备注：{session_notes}\n"
        f"总对话轮数：{len(history)}"
    )

    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        raw = await llm_service._call_llm_with_retry_messages(
            messages,
            user_id=state.get("user_id"),
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = _extract_json(raw)
        summary = InterviewSummary(**data)
        return _render_interview_summary_markdown(summary)
    except Exception as e:
        if not allow_fallback:
            raise
        logger.warning("Interview summary LLM call failed, using fallback: %s", e)
        # Legacy callers may opt into a fallback, but it must not fabricate an
        # assessment. The close contract itself never permits this path.
        topic_count = len(re.findall(r"\[asked\]", session_notes))
        topic_info = (
            f"共覆盖了 {topic_count} 个话题" if topic_count else "没有形成可确认的题目覆盖记录"
        )
        return (
            "**整体表现**：本轮结构化复盘未能生成，因此不对表现作推断。\n\n"
            "**尚未充分评估**：\n"
            f"- {topic_info}，无法据此得出完整结论。\n\n"
            "**改进建议**：\n"
            "- 下一次请围绕一个项目完整说明背景、取舍、结果和复盘，以便获得基于证据的反馈。\n\n"
            "**覆盖说明**：本次仅保留已记录的对话事实。"
        )


async def _forced_closing_response(state: ChatState) -> str:
    """Hard-stop overlong interviews so ReAct cannot drift back to tech rounds.

    Now generates a structured LLM-based summary instead of hardcoded text.
    """
    message_count = len(state.get("message_history", []) or [])
    config = state.get("decision_config") or DecisionConfig()
    if message_count <= config.hard_stop_message_count:
        return ""

    state["question_source"] = "conversation"
    state["question_source_reason"] = "forced_closing_by_message_count"

    return await _generate_structured_summary(state)


async def _generate_end_interview_response(state: ChatState) -> str:
    """Generate a closing response when the user explicitly requests end_interview.

    This function is called when intent == 'end_interview'.  It MUST NOT call
    any tools (load_skill / search_questions / draw_questions).  It produces
    a structured LLM-generated summary. Natural closing wording is owned by
    closing_writer in the close_with_summary contract.

    Side-effects on *state*:
    - Sets question_source / question_source_reason for metadata.
    - Sets question_source to 'conversation' so downstream doesn't expect a
      selected_question binding.
    """
    state["question_source"] = "conversation"
    state["question_source_reason"] = "end_interview_hard_route"

    return await _generate_structured_summary(state)


def _sanitize_error_message(e: Exception) -> str:
    err_str = str(e).lower()
    if "401" in err_str or "invalid api key" in err_str or "unauthorized" in err_str:
        return _FRIENDLY_ERROR
    return f"处理消息时出现错误: {str(e)}"

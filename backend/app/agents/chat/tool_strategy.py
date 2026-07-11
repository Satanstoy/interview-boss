"""Declarative tool strategy derived from ChatState.

Replaces the giant _build_tool_strategy if/elif tree in nodes.py with a
query over typed state fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.chat.state import ChatState


@dataclass(frozen=True)
class ToolStrategy:
    """What the ReAct loop is allowed and expected to do this turn."""

    requires_retrieval: bool = False
    allow_search: bool = True
    allow_draw: bool = True
    allow_load_skill: bool = True
    allowed_skills: list[str] = field(default_factory=list)
    instruction: str = ""
    next_phase_hint: str = ""

    def to_prompt_text(self) -> str:
        """Render as the <tool_strategy> block injected into system prompt."""
        lines = ["<tool_strategy>"]
        if self.instruction:
            lines.append(self.instruction)
        if self.requires_retrieval:
            lines.append("当前状态：需要先调用题库工具获取候选题。")
            lines.append(
                "执行要求：下一步必须先发起允许的 tool call，不能直接输出自然语言问题；"
                "拿到工具结果后再组织面试官提问。"
            )
            lines.append(
                "搜索策略：搜 1-2 次不同维度即可，不要反复搜索相同或相似主题。"
                "拿到候选题后，从中选出最适合当前对话的一道，"
                "结合候选人刚才的回答改写成自然追问，然后直接输出。"
                "不要为了「找更好的题」而无限搜索——题库质量靠你挑选和改写，不靠搜索次数。"
            )
            if self.allow_search and self.allow_draw:
                lines.append("允许：search_questions 或 draw_questions。")
            elif self.allow_search:
                lines.append("必须：调用 search_questions。")
            elif self.allow_draw:
                lines.append("必须：调用 draw_questions。")
            else:
                lines.append("注意：没有可用的检索工具，请直接生成回应。")
        else:
            lines.append("当前状态：不需要调用题库工具。")
        if not self.allow_search:
            lines.append("禁止：search_questions。")
        if not self.allow_draw:
            lines.append("禁止：draw_questions。")
        if not self.allow_load_skill:
            lines.append("禁止：load_skill。")
        if self.allowed_skills:
            lines.append(f"建议加载 skill：{', '.join(self.allowed_skills)}")
        if self.next_phase_hint:
            lines.append(f"下一方向提示：{self.next_phase_hint}")
        lines.append("</tool_strategy>")
        return "\n".join(lines)


def _harness_focus(state: "ChatState") -> dict:
    """Best-effort read of big-tech full-loop focus without adding deps."""
    interview_state = state.get("interview_state") or {}
    if not isinstance(interview_state, dict):
        return {}
    next_focus = interview_state.get("next_focus") or ""
    coverage = interview_state.get("coverage") or {}
    # If coverage is a dict with missing phases, surface the first gap.
    missing = ""
    if isinstance(coverage, dict):
        for phase, data in coverage.items():
            if isinstance(data, dict):
                current = data.get("current_count", 0)
                threshold = data.get("threshold", 0)
                if current < threshold:
                    missing = phase
                    break
    return {
        "phase": interview_state.get("current_phase", ""),
        "next_focus": next_focus,
        "missing_phase": missing,
    }


def _active_skill_names(state: "ChatState") -> list[str]:
    return list(state.get("active_skills") or [])


def compute_tool_strategy(state: "ChatState") -> ToolStrategy:
    """Return the tool strategy for the current turn based purely on state."""
    from app.agents.chat.decision_config import DecisionConfig

    intent = state.get("intent", "interview_question")
    answer_quality = state.get("answer_quality", "complete")
    should_retrieve = bool(state.get("should_retrieve", False))
    requires_bank = bool(state.get("requires_bank_question", False))
    has_candidates = bool(
        state.get("retrieved_questions") or state.get("candidate_questions")
    )
    escalation = state.get("escalation_level", 0)
    off_topic = state.get("off_topic_streak", 0)
    repetition = state.get("repetition_streak", 0)
    active_skills = _active_skill_names(state)
    config = state.get("decision_config") or DecisionConfig()
    message_count = len(state.get("message_history", []) or [])
    harness = _harness_focus(state)
    turn_intent = state.get("turn_intent") or {}

    # End interview: no tools at all.
    if intent == "end_interview":
        return ToolStrategy(
            requires_retrieval=False,
            allow_search=False,
            allow_draw=False,
            allow_load_skill=False,
            instruction="当前状态：用户要求结束面试。严格禁止调用任何工具，直接生成总结或收尾。",
        )

    if (
        isinstance(turn_intent, dict)
        and turn_intent.get("strategy") == "topic_shift"
        and (turn_intent.get("tool_intent") or {}).get("requires_question_bank")
    ):
        target_dimension = str(turn_intent.get("target_dimension") or "")
        return ToolStrategy(
            requires_retrieval=True,
            allow_search=False,
            allow_draw=True,
            allow_load_skill=False,
            instruction="当前状态：节奏策略已决定切换评估维度。必须从目标维度抽题，不能继续当前项目搜索。",
            next_phase_hint=target_dimension,
        )

    if (
        isinstance(turn_intent, dict)
        and turn_intent.get("strategy") == "deep_dive"
        and not (turn_intent.get("tool_intent") or {}).get("requires_question_bank")
    ):
        return ToolStrategy(
            requires_retrieval=False,
            allow_search=False,
            allow_draw=False,
            allow_load_skill=False,
            instruction="当前状态：节奏策略要求围绕已有项目证据深挖，不调用题库工具。",
            next_phase_hint=str(turn_intent.get("drill_layer") or "project_followup"),
        )

    # Wrap-up / strong close: do not start new topics.
    if harness.get("phase") == "wrap_up" or message_count >= config.strong_close_message_count:
        return ToolStrategy(
            requires_retrieval=False,
            allow_search=False,
            allow_draw=False,
            allow_load_skill=True,
            instruction="当前状态：面试进入收尾阶段。只补最后缺口或进入 HR/反问/收尾，禁止出新题。",
            next_phase_hint=harness.get("missing_phase") or "收尾",
        )

    # Topic escalation / repetition / off-topic excess: force a pivot via draw.
    if escalation >= 3 or off_topic >= 3 or repetition >= 2:
        return ToolStrategy(
            requires_retrieval=True,
            allow_search=False,
            allow_draw=True,
            allow_load_skill=True,
            allowed_skills=["interview-rhythm"],
            instruction="当前状态：同一话题追问已超限或候选人重复/答非所问。必须切换到完全不同的面试方向。",
            next_phase_hint=harness.get("next_focus") or "新方向",
        )

    # Incomplete / off-topic / repeated answer: do not retrieve, handle in-place.
    if answer_quality in ("incomplete", "off_topic", "repeated"):
        instruction = "当前状态：候选人回答"
        if answer_quality == "incomplete":
            instruction += "不完整，继续追问细节，不要检索新题。"
        elif answer_quality == "off_topic":
            instruction += "答非所问，指出问题并要求重新回答；不要检索新题。"
        else:
            instruction += "重复，指出重复并考虑切换方向；不要检索新题。"
        return ToolStrategy(
            requires_retrieval=False,
            allow_search=False,
            allow_draw=False,
            allow_load_skill=True,
            instruction=instruction,
        )

    # Practice request: always retrieve.
    if intent == "practice_request":
        return ToolStrategy(
            requires_retrieval=True,
            allow_search=True,
            allow_draw=True,
            allow_load_skill=True,
            instruction="当前状态：用户请求练习。调用 search_questions 或 draw_questions 出题。",
        )

    # Chat / follow-up: no retrieval unless we already have candidates.
    if intent in ("chat", "follow_up"):
        return ToolStrategy(
            requires_retrieval=False,
            allow_search=has_candidates,
            allow_draw=has_candidates,
            allow_load_skill=True,
            instruction="当前状态：闲聊或追问。直接回应，如需补充题目再调用工具。",
        )

    # interview_question branch
    if not has_candidates and (should_retrieve or requires_bank):
        is_deep_dive = "project-deep-dive" in active_skills
        question_type = state.get("question_type")
        if question_type == "algorithm_coding" or harness.get("phase") == "algorithm_coding":
            return ToolStrategy(
                requires_retrieval=True,
                allow_search=False,
                allow_draw=True,
                allow_load_skill=True,
                allowed_skills=["algorithm-coding"],
                instruction="当前状态：需要一道算法/手撕代码题。调用 draw_questions(question_type='algorithm_coding')。",
                next_phase_hint="algorithm_coding",
            )
        if is_deep_dive:
            return ToolStrategy(
                requires_retrieval=True,
                allow_search=True,
                allow_draw=False,
                allow_load_skill=True,
                allowed_skills=["project-deep-dive"],
                instruction="当前状态：项目深挖模式。从用户回答中提取关键词调用 search_questions。",
                next_phase_hint="project_followup",
            )
        # Default: retrieve related questions.
        next_phase = harness.get("next_focus") or question_type or "相关技术"
        return ToolStrategy(
            requires_retrieval=True,
            allow_search=True,
            allow_draw=harness.get("phase") not in ("project_followup",),
            allow_load_skill=True,
            instruction="当前状态：用户回答完毕，需要检索追问题。从回答中提取关键词调用 search_questions。",
            next_phase_hint=str(next_phase),
        )

    # We already have candidates: stay natural.
    if has_candidates:
        return ToolStrategy(
            requires_retrieval=False,
            allow_search=False,
            allow_draw=False,
            allow_load_skill=True,
            instruction="当前状态：已有候选题。直接使用已有题目追问，无需再次检索。",
        )

    # Fallback for interview_question without retrieval requirement.
    return ToolStrategy(
        requires_retrieval=False,
        allow_search=False,
        allow_draw=False,
        allow_load_skill=True,
        instruction="当前状态：基于已有上下文做自然追问，不需要题库工具。",
    )

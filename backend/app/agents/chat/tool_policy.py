"""Execution-time authorization for ReAct tools.

``ToolStrategy`` is intentionally still used to describe the desired behavior
to the model.  This module turns that strategy into a small immutable policy
that is checked immediately before each tool call is dispatched.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.agents.chat.state import ChatState
from app.agents.chat.tool_gateway import validate_tool_arguments
from app.agents.chat.tool_strategy import compute_tool_strategy
from app.agents.chat.agent_profile import is_agent_development_profile


TOOL_POLICY_VERSION = "chat-tool-policy-v1"
REGISTERED_TOOLS = frozenset(
    {
        "load_skill",
        "search_questions",
        "draw_questions",
        "select_question",
        "search_agent_private_questions",
        "draw_agent_private_questions",
        "select_agent_private_question",
    }
)


class ToolPolicyViolation(ValueError):
    """A tool call failed at the shared execution authorization boundary."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolPolicy:
    """The tools and skill scope allowed for one current ReAct state."""

    user_id: int
    conversation_id: str
    bank_mode: str
    allowed_tools: frozenset[str]
    # ``None`` means all registered skills; an empty set means no skills.
    allowed_skills: frozenset[str] | None
    policy_version: str = TOOL_POLICY_VERSION

    def allows(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools

    def allows_skill(self, skill_name: str) -> bool:
        return self.allowed_skills is None or skill_name in self.allowed_skills


def build_tool_policy(state: ChatState) -> ToolPolicy:
    """Derive an execution policy from the current, server-owned state."""

    strategy = compute_tool_strategy(state)
    allowed_tools: set[str] = set()

    if strategy.allow_search:
        allowed_tools.add("search_questions")
    if strategy.allow_draw:
        allowed_tools.add("draw_questions")
    if strategy.allow_load_skill:
        allowed_tools.add("load_skill")

    private_enabled = is_agent_development_profile(state) and not state.get("_mcp_external")
    if private_enabled and strategy.allow_search:
        allowed_tools.add("search_agent_private_questions")
    if private_enabled and strategy.allow_draw:
        allowed_tools.add("draw_agent_private_questions")

    if state.get("candidate_questions") or state.get("retrieved_questions"):
        allowed_tools.add("select_question")
        if private_enabled and state.get("question_source") == "agent_internal":
            allowed_tools.add("select_agent_private_question")

    allowed_skills: frozenset[str] | None
    if not strategy.allow_load_skill:
        allowed_skills = frozenset()
    elif strategy.allowed_skills:
        skills = set(strategy.allowed_skills)
        if private_enabled:
            skills.add("agent-interview")
        allowed_skills = frozenset(skills)
    else:
        allowed_skills = None if not private_enabled else frozenset(
            {
                "interview-tool-use",
                "adaptive-difficulty",
                "algorithm-coding",
                "hr-soft-skills",
                "interview-rhythm",
                "project-deep-dive",
                "theory-qa",
                "agent-interview",
            }
        )

    return ToolPolicy(
        user_id=int(state.get("user_id") or 0),
        conversation_id=str(state.get("conversation_id") or ""),
        bank_mode=str(state.get("bank_mode") or "all"),
        allowed_tools=frozenset(allowed_tools),
        allowed_skills=allowed_skills,
    )


def enforce_tool_call(
    tool_call: dict[str, Any],
    state: ChatState,
    policy: ToolPolicy | None = None,
) -> dict[str, Any]:
    """Validate and normalize a tool call immediately before dispatch.

    This is intentionally shared by the ReAct validator and the executor. The
    executor must remain safe when a caller bypasses the ReAct loop.
    """
    active_policy = policy or build_tool_policy(state)
    function = tool_call.get("function") if isinstance(tool_call, dict) else None
    if not isinstance(function, dict):
        raise ToolPolicyViolation(
            "INVALID_TOOL_ARGUMENTS", "tool call is missing function object"
        )

    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise ToolPolicyViolation(
            "INVALID_TOOL_ARGUMENTS", "tool call is missing tool name"
        )
    if name not in REGISTERED_TOOLS:
        raise ToolPolicyViolation("UNKNOWN_TOOL", f"Unknown tool: {name}")
    if not active_policy.allows(name):
        raise ToolPolicyViolation(
            "TOOL_NOT_ALLOWED", f"Tool is not allowed in the current policy: {name}"
        )

    if name in {
        "search_agent_private_questions",
        "draw_agent_private_questions",
        "select_agent_private_question",
    } and (state.get("_mcp_external") or not is_agent_development_profile(state)):
        raise ToolPolicyViolation(
            "PRIVATE_TOOL_NOT_ALLOWED",
            "Agent private tools require the internal Agent interview profile",
        )

    raw_args = function.get("arguments", "{}")
    try:
        normalized_args = validate_tool_arguments(name, raw_args)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ToolPolicyViolation(
            "INVALID_TOOL_ARGUMENTS", f"Invalid arguments for {name}: {exc}"
        ) from exc

    if name == "load_skill":
        skill_name = normalized_args.get("skill_name", "")
        if not active_policy.allows_skill(skill_name):
            raise ToolPolicyViolation(
                "SKILL_NOT_ALLOWED", f"Skill is not allowed in the current policy: {skill_name}"
            )

    validated = dict(tool_call)
    validated_function = dict(function)
    validated_function["arguments"] = json.dumps(
        normalized_args, ensure_ascii=False, separators=(",", ":")
    )
    validated["function"] = validated_function
    return validated

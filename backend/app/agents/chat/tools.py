"""ReAct agent tool schemas and executor for the chat agent.

Defines 3 tools the LLM can call via OpenAI function calling:
- load_skill: Load a skill's full instruction by name
- search_questions: FTS5 hybrid search for interview questions
- draw_questions: Weighted random question drawing
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.agents.chat.state import ChatState

logger = logging.getLogger(__name__)


# ── Dependency Injection (for easy test mocking) ──────────

def _get_skill_registry():
    """Lazy import to avoid circular dependencies."""
    from app.agents.chat.skills import get_default_registry

    return get_default_registry()


def _hybrid_search(**kwargs):
    """Lazy import wrapper for hybrid_search."""
    from app.services.fts_service import hybrid_search

    return hybrid_search(**kwargs)


def _draw_questions(**kwargs):
    """Lazy import wrapper for draw_questions."""
    from app.services.question_draw_service import draw_questions

    return draw_questions(**kwargs)


# ── Tool Schemas (OpenAI function calling format) ────────

SKILL_NAMES = [
    "adaptive-difficulty",
    "algorithm-coding",
    "hr-soft-skills",
    "interview-rhythm",
    "project-deep-dive",
    "theory-qa",
]

LOAD_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "加载面试技能的完整指导。技能指令将注入到当前 ReAct loop 的系统提示中。\n\n"
            "【何时使用】\n"
            "- 需要切换面试模式（如从普通问答切到项目深挖）\n"
            "- 用户的回答涉及需要特殊追问策略的领域（算法、HR、项目经历）\n"
            "- 当前面试节奏需要调整（如难度过高/过低）\n\n"
            "【何时不用】\n"
            "- 技能已在 active_skills 中（不要重复加载）\n"
            "- 普通知识问答不需要特殊技能\n"
            "- 用户在闲聊"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "enum": SKILL_NAMES,
                    "description": (
                        "要加载的技能名称。各技能用途：\n"
                        "- adaptive-difficulty: 动态调整面试难度\n"
                        "- algorithm-coding: 手撕代码/算法题面试\n"
                        "- hr-soft-skills: HR 行为面试/软技能\n"
                        "- interview-rhythm: 面试节奏控制（始终激活）\n"
                        "- project-deep-dive: 项目经历深度追问\n"
                        "- theory-qa: 技术理论问答"
                    ),
                },
            },
            "required": ["skill_name"],
        },
    },
}

SEARCH_QUESTIONS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_questions",
        "description": (
            "从面试题库中搜索相关题目。返回匹配的题目及元数据（分类、难度等）。\n\n"
            "【何时使用】\n"
            "- 用户提交了回答，需要追问题（intent=interview_question, answer_complete=true）\n"
            "- 需要特定技术主题的题目（如「Redis 持久化」「微服务拆分」）\n"
            "- 用户请求练习某类题目（intent=practice_request）\n\n"
            "【何时不用】\n"
            "- 用户在闲聊或还没回答完（intent=chat 或 answer_complete=false）\n"
            "- 已有未使用的检索结果（retrieved_questions 非空）\n"
            "- 用户明确要求跳过或换话题\n\n"
            "【参数示例】\n"
            "- 追问项目：keywords=['微服务', '服务拆分', 'DDD'], question_type='project_followup'\n"
            "- 知识探测：keywords=['Redis', '持久化', 'RDB'], question_type='knowledge_probe'\n"
            "- 新话题：keywords=['算法', '动态规划'], question_type='new_question'\n\n"
            "【如何使用返回结果】\n"
            "- 工具返回 top 3 候选题。选择最贴近当前对话的一题，改写成自然的面试官追问。\n"
            "- 不要机械复述题库原文；要结合候选人刚才的回答承接发问。\n"
            "- 如果结果和当前回答不匹配，可以忽略检索结果并直接追问。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-5 个具体技术术语或主题短语。从用户回答或对话上下文中提取。避免泛词如「技术」「问题」「项目」。",
                },
                "question_type": {
                    "type": "string",
                    "enum": ["project_followup", "knowledge_probe", "new_question"],
                    "description": "project_followup: 深挖用户项目回答。knowledge_probe: 探测理论理解。new_question: 切换新话题。",
                },
            },
            "required": ["keywords"],
        },
    },
}

DRAW_QUESTIONS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "draw_questions",
        "description": (
            "从题库中加权随机抽取题目。用于需要新鲜题目的场景。\n\n"
            "【何时使用】\n"
            "- search_questions 结果不足或为空时补充\n"
            "- 用户请求「随机出题」「来几道题」\n"
            "- 需要跨话题混合出题\n\n"
            "【何时不用】\n"
            "- 已有未使用的检索结果\n"
            "- 需要特定技术主题的题目（应优先用 search_questions）\n"
            "- 用户在闲聊或还没回答完"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "抽取题目数量，默认 3，最大 5",
                    "default": 3,
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "难度筛选。不指定则根据用户水平自动加权。",
                },
            },
        },
    },
}

ALL_TOOLS = [LOAD_SKILL_SCHEMA, SEARCH_QUESTIONS_SCHEMA, DRAW_QUESTIONS_SCHEMA]


# ── Progress Messages ────────────────────────────────────

def tool_progress_message(tool_call: dict) -> str:
    """Return a user-visible progress string based on tool name."""
    name = tool_call.get("function", {}).get("name", "")
    args = {}
    try:
        args = json.loads(tool_call.get("function", {}).get("arguments", "{}") or "{}")
    except Exception:
        args = {}
    skill_labels = {
        "adaptive-difficulty": "自适应难度策略",
        "algorithm-coding": "算法面试策略",
        "hr-soft-skills": "HR 软技能策略",
        "interview-rhythm": "面试节奏策略",
        "project-deep-dive": "项目深挖策略",
        "theory-qa": "理论问答策略",
    }
    skill_label = skill_labels.get(args.get("skill_name"), "面试策略")
    messages = {
        "load_skill": f"正在加载{skill_label}...",
        "search_questions": "正在检索相关面试题...",
        "draw_questions": "正在从题库抽题...",
    }
    return messages.get(name, "正在处理...")


# ── Executor ─────────────────────────────────────────────

async def execute_tool(tool_call: dict, state: ChatState) -> str:
    """Execute a tool call and return the result as a JSON string.

    Args:
        tool_call: The tool call dict with function.name and function.arguments
        state: The current ChatState (some tools may update state in-place)

    Returns:
        JSON-encoded result string
    """
    try:
        func_name = tool_call.get("function", {}).get("name", "")
        args = json.loads(tool_call.get("function", {}).get("arguments", "{}"))

        if func_name == "load_skill":
            return _execute_load_skill(args, state)
        elif func_name == "search_questions":
            return await _execute_search_questions(args, state)
        elif func_name == "draw_questions":
            return await _execute_draw_questions(args, state)
        else:
            return json.dumps({"error": f"Unknown tool: {func_name}"})
    except Exception as e:
        logger.exception("Error executing tool")
        return json.dumps({"error": str(e)})


# ── Tool Implementations ─────────────────────────────────

def _execute_load_skill(args: dict, state: ChatState) -> str:
    """Load a skill's instruction, store as current-loop pending system prompt injection."""
    skill_name = args.get("skill_name", "")
    registry = _get_skill_registry()
    skill = registry.get(skill_name)

    if skill is None:
        return json.dumps({"error": f"Unknown skill: {skill_name}"})

    # Already active — skip
    active_skills = state.setdefault("active_skills", [])
    if skill_name in active_skills:
        return json.dumps({"status": "already_active", "skill": skill_name})

    # Mark active
    active_skills.append(skill_name)

    # Store instruction for current-loop system prompt injection (not as tool result)
    instruction = skill.get_instruction()
    if instruction:
        state.setdefault("active_skill_instructions", []).append({
            "skill_name": skill_name,
            "instruction": instruction,
        })

    return json.dumps({
        "status": "loaded",
        "skill": skill_name,
        "summary": f"技能「{skill.description}」已激活，将注入到当前 ReAct loop 的系统提示中。",
    })


async def _execute_search_questions(args: dict, state: ChatState) -> str:
    """Search questions via hybrid_search, update state, return top 3."""
    search_args: dict[str, Any] = {
        "keywords": args.get("keywords", []),
    }
    if state.get("search_query"):
        search_args["query_text"] = state["search_query"]
    if args.get("question_type"):
        search_args["question_type"] = args["question_type"]
    if state.get("question_type") and "question_type" not in search_args:
        search_args["question_type"] = state["question_type"]
    if state.get("job_position"):
        search_args["job_position"] = state["job_position"]
    if state.get("retrieval_intent"):
        search_args["retrieval_intent"] = state["retrieval_intent"]
    if state.get("search_negative_terms"):
        search_args["negative_terms"] = state["search_negative_terms"]
    if state.get("retrieved_questions"):
        exclude_ids = {
            q.get("id")
            for q in state["retrieved_questions"]
            if isinstance(q, dict) and q.get("id")
        }
        if exclude_ids:
            search_args["exclude_ids"] = exclude_ids

    results = await asyncio.to_thread(_hybrid_search, **search_args)
    state["retrieved_questions"] = results
    return json.dumps(results[:3])


async def _execute_draw_questions(args: dict, state: ChatState) -> str:
    """Draw random questions, update state, return results."""
    user_id = state.get("user_id")
    if not user_id:
        return json.dumps({"error": "user_id is required for draw_questions"})

    draw_args: dict[str, Any] = {
        "user": {
            "id": user_id,
            "bank_mode": state.get("bank_mode", "public"),
        },
        "count": args.get("count", 3),
    }
    if args.get("difficulty"):
        draw_args["difficulty"] = args["difficulty"]
    if state.get("retrieved_questions"):
        exclude_ids = {
            q.get("id")
            for q in state["retrieved_questions"]
            if isinstance(q, dict) and q.get("id")
        }
        if exclude_ids:
            draw_args["exclude_ids"] = exclude_ids

    results = await asyncio.to_thread(_draw_questions, **draw_args)
    state["retrieved_questions"] = results
    return json.dumps(results)

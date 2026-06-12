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
        "description": "Load a skill's full instruction by name. Use this to get detailed guidance on how to conduct a specific type of interview.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "enum": SKILL_NAMES,
                    "description": "The name of the skill to load",
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
        "description": "Search the interview question bank using keywords. Returns matching questions with metadata (category, difficulty, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Search keywords for finding relevant interview questions",
                },
                "question_type": {
                    "type": "string",
                    "enum": ["project_followup", "knowledge_probe", "new_question"],
                    "description": "Optional filter by question type",
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
        "description": "Draw weighted random questions from the question bank. Use when you need fresh questions not found via search.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of questions to draw (default: 3)",
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "Filter by difficulty level",
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
    messages = {
        "load_skill": "Loading interview skill guidance...",
        "search_questions": "Searching for interview questions...",
        "draw_questions": "Drawing random practice questions...",
    }
    return messages.get(name, f"Executing {name}...")


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
            return _execute_load_skill(args)
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

def _execute_load_skill(args: dict) -> str:
    """Load a skill's instruction from the registry."""
    skill_name = args.get("skill_name", "")
    registry = _get_skill_registry()
    skill = registry.get(skill_name)

    if skill is None:
        return json.dumps({"error": f"Unknown skill: {skill_name}"})

    return json.dumps({"instruction": skill.get_instruction()})


async def _execute_search_questions(args: dict, state: ChatState) -> str:
    """Search questions via hybrid_search, update state, return top 3."""
    search_args: dict[str, Any] = {"keywords": args.get("keywords", [])}
    if args.get("question_type"):
        search_args["question_type"] = args["question_type"]

    results = await asyncio.to_thread(_hybrid_search, **search_args)
    state["retrieved_questions"] = results
    return json.dumps(results[:3])


async def _execute_draw_questions(args: dict, state: ChatState) -> str:
    """Draw random questions, update state, return results."""
    user_id = state.get("user_id")
    if not user_id:
        return json.dumps({"error": "user_id is required for draw_questions"})

    draw_args: dict[str, Any] = {
        "user": {"id": user_id},
        "count": args.get("count", 3),
    }
    if args.get("difficulty"):
        draw_args["difficulty"] = args["difficulty"]

    results = await asyncio.to_thread(_draw_questions, **draw_args)
    state["retrieved_questions"] = results
    return json.dumps(results)

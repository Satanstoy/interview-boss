"""ReAct agent tool schemas and executor for the chat agent.

Defines 3 tools the LLM can call via OpenAI function calling:
- load_skill: Load a skill's full instruction by name
- search_questions: FTS5 hybrid search for interview questions
- draw_questions: Weighted random question drawing
"""

from __future__ import annotations

import json
import logging

from app.agents.chat.state import ChatState

logger = logging.getLogger(__name__)

# Relevance threshold for LLM rerank scores
_RERANK_RELEVANCE_THRESHOLD = 0.3


def _parse_rerank_scores(raw: str) -> list[float]:
    """Extract rerank scores from strict JSON or JSON embedded in model prose."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty rerank response")

    decoder = json.JSONDecoder()
    starts = [idx for idx, char in enumerate(text) if char in "[{"]
    for start in starts:
        try:
            parsed, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            scores = parsed.get("scores")
        else:
            scores = parsed
        if isinstance(scores, list):
            return [float(score) for score in scores]

    raise ValueError("rerank response does not contain a JSON scores array")


# ── Dependency Injection (for easy test mocking) ──────────


def _get_skill_registry():
    """Lazy import to avoid circular dependencies."""
    from app.agents.chat.skills import get_default_registry

    return get_default_registry()


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
            "- 用户要求写代码、进入算法题环节，或需要全新题目\n"
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
                "cat1": {
                    "type": "string",
                    "description": "一级分类筛选，如 B.Agent与LLM应用、E.算法与数据结构。可选。",
                },
                "cat2": {
                    "type": "string",
                    "description": "二级分类筛选，如 E2.算法手撕、B2.RAG系统设计。可选。",
                },
                "topic": {
                    "type": "string",
                    "description": "希望抽取的主题关键词，如 TopK、RAG、MCP、二分查找。可选。",
                },
                "question_type": {
                    "type": "string",
                    "enum": [
                        "algorithm_coding",
                        "project_followup",
                        "knowledge_probe",
                        "system_design",
                        "hr",
                    ],
                    "description": "抽题场景。algorithm_coding 必须用于手撕代码题。",
                },
            },
        },
    },
}

SELECT_QUESTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "select_question",
        "description": (
            "从 search_questions 或 draw_questions 返回的候选题中，绑定一道作为下一题计划。\n\n"
            "【何时使用】\n"
            "- 已经调用 search_questions / draw_questions 获得候选题\n"
            "- 需要显式从候选题中选择一道并生成 question_plan\n"
            "- 默认选择逻辑（第一题）不符合当前对话 intent\n\n"
            "【何时不用】\n"
            "- 还没有候选题（应先调用 search_questions 或 draw_questions）\n"
            "- 用户只是在闲聊"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "candidate_index": {
                    "type": "integer",
                    "description": "候选题索引，0 表示第一题。默认 0。",
                    "default": 0,
                },
            },
        },
    },
}

ALL_TOOLS = [
    LOAD_SKILL_SCHEMA,
    SEARCH_QUESTIONS_SCHEMA,
    DRAW_QUESTIONS_SCHEMA,
    SELECT_QUESTION_SCHEMA,
]


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
        "select_question": "正在绑定下一题...",
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
        elif func_name == "select_question":
            return _execute_select_question(args, state)
        else:
            return json.dumps({"error": f"Unknown tool: {func_name}"})
    except Exception as e:
        logger.exception("Error executing tool")
        return json.dumps({"error": str(e)})


# ── Tool Implementations ─────────────────────────────────


def _execute_load_skill(args: dict, state: ChatState) -> str:
    """Load a skill through the backend MCP tool boundary."""
    from app.mcp_server.interview_tools import load_skill_tool

    result = load_skill_tool(args, state, registry_getter=_get_skill_registry)
    return json.dumps(result, ensure_ascii=False)


async def _llm_rerank_in_tool(
    candidates: list[dict],
    conversation_context: str,
    user_id: int,
    model: str = None,
) -> list[dict] | None:
    """LLM-based reranking inside search_questions tool.

    Uses the LLM to score candidate questions by relevance to the current
    conversation context. Filters by _RERANK_RELEVANCE_THRESHOLD.
    Returns None on failure so callers can preserve the original tool envelope.
    """
    if len(candidates) < 3:
        return candidates

    candidate_text = "\n".join(
        f"{i+1}. [{q.get('cat1', '')}/{q.get('cat2', '')}] {q.get('question', '')}"
        for i, q in enumerate(candidates[:15])
    )

    prompt = (
        "根据以下面试对话上下文，对候选题目的相关性评分（0-1）。\n"
        "只输出一个JSON对象，不要解释，不要使用Markdown。\n\n"
        f"对话上下文：\n{conversation_context[:500]}\n\n"
        f"候选题目：\n{candidate_text}\n\n"
        '输出格式：{"scores": [0.9, 0.3, 0.8]}，scores长度必须与候选题数量一致。'
    )

    try:
        from app.services.llm import raw_llm_call

        result = await raw_llm_call(
            user_id=user_id,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是面试题相关性打分器。必须只返回JSON对象，"
                        '格式为{"scores":[数字数组]}。'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        scores = _parse_rerank_scores(result)

        for i, q in enumerate(candidates[: len(scores)]):
            q["_relevance_score"] = float(scores[i])

        filtered = [
            q
            for q in candidates
            if q.get("_relevance_score", 0) >= _RERANK_RELEVANCE_THRESHOLD
        ]
        filtered.sort(key=lambda q: q.get("_relevance_score", 0), reverse=True)

        if filtered:
            logger.info(
                "LLM rerank: %d/%d candidates above threshold %.1f",
                len(filtered),
                len(candidates),
                _RERANK_RELEVANCE_THRESHOLD,
            )
            return filtered[:5]

        logger.info("LLM rerank: all candidates below threshold, using top 3")
        return candidates[:3]

    except Exception as e:
        logger.warning("LLM rerank in search_questions failed: %s", e)
        return None


async def _execute_search_questions(args: dict, state: ChatState) -> str:
    """Search questions through the backend MCP tool boundary."""
    from app.mcp_server.interview_tools import search_questions_tool

    envelope = await search_questions_tool(args, state)

    # LLM rerank: score candidates by relevance to conversation context
    questions = envelope.get("items", [])
    if len(questions) >= 3:
        recent = state.get("recent_messages", [])
        context = "\n".join(
            f"{'面试官' if m.get('role') == 'assistant' else '候选人'}: "
            f"{m.get('content', '')[:100]}"
            for m in recent[-4:]
        )
        reranked = await _llm_rerank_in_tool(
            questions, context, state["user_id"], state.get("model")
        )
        if reranked is not None:
            envelope["items"] = reranked
            envelope.setdefault("metadata", {})["result_count"] = len(reranked)
            state["candidate_questions"] = reranked
            state["retrieved_questions"] = reranked

    return json.dumps(envelope, ensure_ascii=False)


async def _execute_draw_questions(args: dict, state: ChatState) -> str:
    """Draw questions through the backend MCP tool boundary."""
    from app.mcp_server.interview_tools import draw_questions_tool

    envelope = await draw_questions_tool(args, state)
    return json.dumps(envelope, ensure_ascii=False)


def _execute_select_question(args: dict, state: ChatState) -> str:
    """Select and bind one candidate as the next-question plan."""
    from app.mcp_server.interview_tools import select_question_tool

    candidate_index = args.get("candidate_index", 0)
    envelope = select_question_tool(args, state, candidate_index=candidate_index)
    return json.dumps(envelope, ensure_ascii=False)

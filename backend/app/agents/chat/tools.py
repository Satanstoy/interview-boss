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
                        "behavioral",
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

AGENT_PRIVATE_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_agent_private_questions",
        "description": (
            "仅限 Agent 开发面试内部使用：从服务端私有 Agent 能力目录检索候选题。"
            "返回题干和面试官内部评估要点；不得向候选人透露题库、Skill 或内部评分规则。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                },
                "question_type": {
                    "type": "string",
                    "enum": ["system_design", "knowledge_probe"],
                },
                "interview_format": {
                    "type": "string",
                    "enum": [
                        "concept",
                        "system_design",
                        "code_review",
                        "protocol_review",
                    ],
                },
                "capability": {"type": "string"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 5},
            },
            "required": ["keywords"],
        },
    },
}

AGENT_PRIVATE_DRAW_SCHEMA = {
    "type": "function",
    "function": {
        "name": "draw_agent_private_questions",
        "description": (
            "仅限 Agent 开发面试内部使用：从私有 Agent 能力目录抽取新题，"
            "用于覆盖尚未评估的 Agent 能力维度。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
                "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                "question_type": {
                    "type": "string",
                    "enum": ["system_design", "knowledge_probe"],
                },
                "interview_format": {
                    "type": "string",
                    "enum": [
                        "concept",
                        "system_design",
                        "code_review",
                        "protocol_review",
                    ],
                },
                "capability": {"type": "string"},
            },
        },
    },
}

AGENT_PRIVATE_SELECT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "select_agent_private_question",
        "description": (
            "仅限 Agent 开发面试内部使用：从私有 Agent 候选集中按索引绑定下一题。"
            "候选集由服务端维护，不能提交自定义题干。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "candidate_index": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "maximum": 4,
                },
            },
        },
    },
}

AGENT_PRIVATE_TOOLS = [
    AGENT_PRIVATE_SEARCH_SCHEMA,
    AGENT_PRIVATE_DRAW_SCHEMA,
    AGENT_PRIVATE_SELECT_SCHEMA,
]


def get_tools_for_state(state: ChatState) -> list[dict]:
    """Expose private schemas only to the internal Agent profile."""
    from app.agents.chat.agent_profile import is_agent_development_profile

    if not is_agent_development_profile(state) or state.get("_mcp_external"):
        return ALL_TOOLS

    private_load_schema = json.loads(json.dumps(LOAD_SKILL_SCHEMA, ensure_ascii=False))
    private_load_schema["function"]["parameters"]["properties"]["skill_name"][
        "enum"
    ] = [
        *SKILL_NAMES,
        "agent-interview",
    ]
    private_load_schema["function"]["parameters"]["properties"]["skill_name"][
        "description"
    ] += "\n- agent-interview: Agent 开发岗位专属内部面试策略（仅当前 Agent profile 可用）"
    return [
        private_load_schema,
        SEARCH_QUESTIONS_SCHEMA,
        DRAW_QUESTIONS_SCHEMA,
        SELECT_QUESTION_SCHEMA,
        *AGENT_PRIVATE_TOOLS,
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
        "search_agent_private_questions": "正在评估 Agent 专项能力...",
        "draw_agent_private_questions": "正在抽取 Agent 专项能力题...",
        "select_agent_private_question": "正在绑定 Agent 专项面试题...",
    }
    return messages.get(name, "正在处理...")


# ── Executor ─────────────────────────────────────────────


async def execute_tool(
    tool_call: dict,
    state: ChatState,
    policy=None,
) -> str:
    """Execute a tool call and return the result as a JSON string.

    Args:
        tool_call: The tool call dict with function.name and function.arguments
        state: The current ChatState (some tools may update state in-place)

    Returns:
        JSON-encoded result string
    """
    try:
        from app.agents.chat.tool_policy import (
            REGISTERED_TOOLS,
            ToolPolicy,
            ToolPolicyViolation,
            build_tool_policy,
            enforce_tool_call,
        )

        if not isinstance(policy, ToolPolicy):
            policy = build_tool_policy(state)
        tool_call = enforce_tool_call(tool_call, state, policy)
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
        elif func_name == "search_agent_private_questions":
            return await _execute_search_agent_private_questions(args, state)
        elif func_name == "draw_agent_private_questions":
            return await _execute_draw_agent_private_questions(args, state)
        elif func_name == "select_agent_private_question":
            return _execute_select_agent_private_question(args, state)
        else:
            return json.dumps({"error": f"Unknown tool: {func_name}"})
    except ToolPolicyViolation as e:
        if e.code == "UNKNOWN_TOOL":
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        tool_name = function.get("name")
        if tool_name in REGISTERED_TOOLS:
            from app.agents.chat.tool_gateway import build_error_envelope

            return json.dumps(
                build_error_envelope(
                    tool=tool_name,
                    error_code=e.code,
                    message=str(e),
                    total_ms=0,
                    debug_reason="validation_failed"
                    if e.code == "INVALID_TOOL_ARGUMENTS"
                    else "policy_denied",
                    empty_reason="invalid_arguments",
                ),
                ensure_ascii=False,
            )
        return json.dumps(
            {"error": {"error_code": e.code, "message": str(e)}},
            ensure_ascii=False,
        )
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
    """LLM-based reranking inside search_questions tool (listwise).

    实验结论（2026-08-06 抽题/检索评估）：listwise（LLM 从候选中选择最相关 top-3）
    比 pointwise（0-1 打分 + 阈值过滤）质量更高（4.2 vs 3.5），且避免 LLM 分数
    波动导致的阈值误判。选中项按原候选顺序保序返回。
    Returns None on failure so callers can preserve the original tool envelope.
    """
    if len(candidates) < 3:
        return candidates

    candidate_text = "\n".join(
        f"{i + 1}. [{q.get('cat1', '')}/{q.get('cat2', '')}] {q.get('question', '')}"
        for i, q in enumerate(candidates[:15])
    )

    prompt = (
        "根据以下面试对话上下文，从候选题中选出最相关的题目（最多 3 道，宁缺毋滥）。\n"
        "只输出一个JSON对象，不要解释，不要使用Markdown。\n\n"
        f"对话上下文：\n{conversation_context[:500]}\n\n"
        f"候选题目：\n{candidate_text}\n\n"
        '输出格式：{"selected_indices": [0, 3, 7]}，selected_indices 是候选题的序号（从 0 开始），'
        "按相关性从高到低排列，最多 3 个。"
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
                        "你是面试题相关性选择器。必须只返回JSON对象，"
                        '格式为{"selected_indices":[整数数组]}。'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        indices = _parse_selected_indices(result, max_idx=len(candidates[:15]))
        if indices is None:
            raise ValueError("rerank response does not contain selected_indices")

        if not indices:
            logger.info("LLM rerank: 未选中任何候选，使用前 3 道")
            return candidates[:3]

        selected = [candidates[i] for i in sorted(indices)]
        logger.info(
            "LLM rerank(listwise): 选中 %d/%d 道", len(selected), len(candidates)
        )
        return selected[:5]

    except Exception as e:
        logger.warning("LLM rerank in search_questions failed: %s", e)
        return None


def _parse_selected_indices(raw: str, max_idx: int) -> list[int] | None:
    """Extract selected_indices from strict JSON or JSON embedded in model prose.

    Returns:
        list[int]: 合法 JSON 中的选中索引（越界/非数字已过滤）
        None: 无法解析出合法 JSON（调用方应视为失败，保留原 envelope）
    """
    text = (raw or "").strip()
    if not text:
        return None

    decoder = json.JSONDecoder()
    starts = [idx for idx, char in enumerate(text) if char in "[{"]
    for start in starts:
        try:
            parsed, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            indices = parsed.get("selected_indices") or parsed.get("selected")
        else:
            indices = parsed
        if isinstance(indices, list):
            out = []
            for idx in indices:
                try:
                    i = int(idx)
                except (TypeError, ValueError):
                    continue
                if 0 <= i < max_idx:
                    out.append(i)
            return out
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


async def _execute_search_agent_private_questions(args: dict, state: ChatState) -> str:
    from app.mcp_server.interview_tools import search_agent_private_questions_tool

    envelope = await search_agent_private_questions_tool(args, state)
    return json.dumps(envelope, ensure_ascii=False)


async def _execute_draw_agent_private_questions(args: dict, state: ChatState) -> str:
    from app.mcp_server.interview_tools import draw_agent_private_questions_tool

    envelope = await draw_agent_private_questions_tool(args, state)
    return json.dumps(envelope, ensure_ascii=False)


def _execute_select_question(args: dict, state: ChatState) -> str:
    """Select and bind one candidate as the next-question plan."""
    from app.mcp_server.interview_tools import select_question_tool

    candidate_index = args.get("candidate_index", 0)
    envelope = select_question_tool(args, state, candidate_index=candidate_index)
    return json.dumps(envelope, ensure_ascii=False)


def _execute_select_agent_private_question(args: dict, state: ChatState) -> str:
    from app.mcp_server.interview_tools import select_agent_private_question_tool

    envelope = select_agent_private_question_tool(args, state)
    return json.dumps(envelope, ensure_ascii=False)

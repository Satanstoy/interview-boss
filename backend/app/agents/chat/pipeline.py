"""Chat Pipeline — 纯 async pipeline，替代 LangGraph StateGraph。

设计原则（来自业界研究）：
- Graph 做基础设施，LLM 做对话决策
- Skills 是 prompt 注入，不是 graph 节点
- 检索结果是参考资料，不是强制约束
- 简单 if/elif 路由，不需要 state machine
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from pydantic import BaseModel

from app.agents.chat.context_builder import build_interview_context
from app.agents.chat.nodes import (
    build_react_system_prompt,
    extract_memory,
    load_history,
    recall_memories,
    summarize_context,
)
from app.agents.chat.tools import (
    ALL_TOOLS,
    SKILL_NAMES,
    execute_tool,
    tool_progress_message,
)
from app.services.llm import (
    _call_llm_with_retry_messages,
    _extract_json,
    llm_with_tools,
    make_tool_result_message,
    stream_llm_messages,
)
from app.agents.chat.state import ChatState
from app.agents.shared.events import _event_queue_var
from app.services import chat_service
from app.services.memory_recall_service import (
    classify_and_recall,
    classify_and_recall_fast,
)

logger = logging.getLogger("interview-boss")

_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"
_SENTINEL = object()
_TRACE_STRING_LIMIT = 120
_TRACE_LIST_LIMIT = 5
_SAFE_TOOL_ARG_KEYS = {
    "cat1",
    "count",
    "difficulty",
    "keywords",
    "question_type",
    "skill_name",
    "topic",
}
_INTERNAL_REACT_MARKERS = frozenset(
    {
        "load_skill",
        "search_questions",
        "draw_questions",
        *SKILL_NAMES,
    }
)

_ALLOWED_TOOL_NAMES = frozenset({"load_skill", "search_questions", "draw_questions"})
_PERSISTENT_SKILLS = frozenset({"interview-rhythm"})


# ── Output Deduplication (hash + Jaccard) ─────────────────


class OutputDeduplicator:
    """Two-level dedup: hash exact match + Jaccard fuzzy match.
    Borrowed from OpenCode ACP (hash) + Manneri (Jaccard)."""

    def __init__(self, window_size: int = 8, jaccard_threshold: float = 0.7):
        self.hash_buffer: set[str] = set()
        self.token_buffer: list[set[str]] = []
        self.window_size = window_size
        self.jaccard_threshold = jaccard_threshold

    def check(self, text: str) -> str:
        """Return 'exact' | 'similar' | 'ok'"""
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        # Level 1: Hash exact match
        h = hashlib.md5(normalized.encode()).hexdigest()
        if h in self.hash_buffer:
            return "exact"
        # Level 2: Jaccard fuzzy match
        tokens = set(normalized.split())
        if len(tokens) >= 5:
            for prev in self.token_buffer:
                union = tokens | prev
                if not union:
                    continue
                jaccard = len(tokens & prev) / len(union)
                if jaccard >= self.jaccard_threshold:
                    return "similar"
        return "ok"

    def record(self, text: str):
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        self.hash_buffer.add(hashlib.md5(normalized.encode()).hexdigest())
        tokens = set(normalized.split())
        self.token_buffer.append(tokens)
        if len(self.token_buffer) > self.window_size:
            self.token_buffer.pop(0)


# ── Structured Interview Summary ────────────────────────────


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
    '- 最弱的话题要给出具体的“答不上来”或“答得浅”的证据\n'
    '- 建议要具体可操作（如“建议复习 LangGraph 的条件路由机制”），'
    '不要给空泛建议（如“继续深度学习”）\n'
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
    if not transcript.strip():
        return ""

    history = state.get("message_history", []) or []
    session_notes = state.get("session_notes", "") or ""

    user_content = (
        "以下是面试记录：\n\n"
        f"{transcript}\n\n"
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


def validate_tool_call(tool_call: dict) -> dict:
    """Validate a tool call from the LLM before execution.

    Enforces allowlist, required fields, and arg type safety.
    Returns the validated tool call dict, or raises StopRun.
    """
    func = tool_call.get("function")
    if not isinstance(func, dict):
        raise StopRun("invalid_tool_call:no_function")

    name = func.get("name")
    if not isinstance(name, str) or not name:
        raise StopRun("invalid_tool_call:missing_name")

    if name not in _ALLOWED_TOOL_NAMES:
        raise StopRun(f"tool_denied:{name}")

    # Validate JSON parseability (downstream expects string format)
    raw_args = func.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            raise StopRun(f"invalid_args:{name}")
    elif not isinstance(raw_args, dict):
        raise StopRun(f"invalid_args:{name}")

    return tool_call  # return original; downstream expects string arguments



# ── ReAct Budget & Control ──────────────────────────────


@dataclass(frozen=True)
class Budget:
    """Three-dimensional runtime budget for the ReAct loop."""

    max_steps: int = 5
    max_tool_calls: int = 10
    max_seconds: float = 30.0


class StopRun(Exception):
    """Raised when the ReAct loop must stop for a governance reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


REACT_BUDGET = Budget()


def _emit(event: dict) -> None:
    queue = _event_queue_var.get()
    if queue:
        queue.put_nowait(event)


def _step(step: str, message: str, reason: str = "", insight: str = "") -> None:
    event: dict = {"type": "step", "step": step, "message": message}
    if reason:
        event["reason"] = reason
    if insight:
        event["insight"] = insight
    _emit(event)


# ── Step reason templates ─────────────────────────────────────
STEP_REASONS = {
    "loading": "加载最近 20 条对话历史和用户记忆，为理解问题提供上下文",
    "context": "构建面试上下文，包含简历和 JD 信息",
    "understanding_first": "首次消息快速分类，确定面试开场策略",
    "understanding_follow": "分析你的回答质量，决定下一步追问方向",
    "load_skill": "根据对话阶段加载对应的面试技巧",
    "search_questions": "根据你的问题关键词，从题库检索相关面试题",
    "draw_questions": "从题库随机抽取一道面试题",
    "generating": "综合上下文和检索结果，生成口述级回答",
    "closing": "面试已达到足够轮次，生成总结评价",
}


def _extract_company(question: dict) -> str:
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except Exception:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("company", "")
    return ""


def _extract_round(question: dict) -> str:
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except Exception:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("round", "")
    return ""


def _public_question(question: dict | None) -> dict | None:
    if not question:
        return None
    return {
        "id": question.get("id"),
        "question": question.get("question", ""),
        "cat1": question.get("cat1", ""),
        "cat2": question.get("cat2", ""),
        "company": _extract_company(question),
        "round": _extract_round(question),
    }


def _tokenize_for_overlap(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}", lowered))
    tokens.update(re.findall(r"[\u4e00-\u9fff]{2,4}", lowered))
    return {t for t in tokens if len(t.strip()) >= 2}


def _normalize_question_text(text: str) -> str:
    return re.sub(
        r"[\s`'\"“”‘’。？?！!，,、：:；;（）()【】\\[\\]{}<>《》]", "", text or ""
    ).lower()


def _infer_selected_question(
    response_text: str,
    basis_question_ids: list[int],
    candidates: list[dict],
) -> tuple[dict | None, str]:
    if not candidates:
        return None, "no_candidate_questions"

    if basis_question_ids:
        basis_id_set = set(basis_question_ids)
        for q in candidates:
            if q.get("id") in basis_id_set:
                return q, "basis_question_id"

    response_norm = _normalize_question_text(response_text)
    if not response_norm:
        return None, "response_has_no_text"

    for q in candidates:
        question_norm = _normalize_question_text(str(q.get("question") or ""))
        if question_norm and (
            question_norm in response_norm
            or (
                len(question_norm) >= 12
                and response_norm in question_norm
                and len(response_norm) / max(len(question_norm), 1) >= 0.75
            )
        ):
            return q, "question_text_match"

    # Single-candidate heuristic: if there's exactly one candidate and the
    # response contains meaningful overlap with its question tokens, bind it.
    # This covers the common case where draw_questions returns 1 question and
    # the LLM uses it without explicit [BASIS] markup.
    if len(candidates) == 1:
        single = candidates[0]
        single_tokens = _tokenize_for_overlap(str(single.get("question") or ""))
        response_tokens = _tokenize_for_overlap(response_text)
        if single_tokens and response_tokens:
            overlap = single_tokens & response_tokens
            # Require at least 2 meaningful token overlaps
            if len(overlap) >= 2:
                return single, "single_candidate_token_overlap"

    return None, "candidate_not_explicitly_used"


def _is_bare_coding_prompt(text: str, state: ChatState) -> bool:
    stripped = (text or "").strip()
    if len(stripped) > 40:
        return False
    wants_coding = (
        "algorithm-coding" in state.get("active_skills", [])
        or state.get("question_type") == "algorithm_coding"
        or bool(re.search(r"(写代码|手撕|代码题|coding)", stripped, re.I))
    )
    if not wants_coding:
        return False
    return bool(re.search(r"(写代码|手撕|代码题|coding)", stripped, re.I))


def _build_previously_asked_section(state: ChatState) -> str:
    """Build a section listing previously asked questions for the current turn.

    Extracts asked questions from session_notes (looked for [asked] entries)
    and message_history (question-like patterns). Returns a formatted string
    to be injected as a user message before the LLM call.
    """
    questions: list[str] = []

    # Extract from session_notes [asked] entries
    session_notes = state.get("session_notes", "")
    for match in re.finditer(r"\[asked\]\s*(.+)", session_notes):
        q = match.group(1).strip()
        if q:
            questions.append(q)

    # Extract from message_history assistant messages that look like question asks
    history = state.get("message_history", []) or []
    for msg in history:
        if msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "")
        for pattern in (
            r"来写一道代码题[：:]\s*(.+?)(?:\n|$)",
            r"来聊一个八股[题：:]\s*(.+?)(?:\n|$)",
            r"我们先收束到一道具体题[：:]\s*(.+?)(?:\n|$)",
            r"说说你对(.+?)的理解",
        ):
            for m in re.finditer(pattern, content):
                q = m.group(1).strip()
                if q:
                    questions.append(q)

    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for q in questions:
        key = q[:30]
        if key not in seen:
            seen.add(key)
            unique.append(q)

    if not unique:
        return ""

    lines = [f"{i}. {q}" for i, q in enumerate(unique, 1)]
    return (
        "[面试状态 - 由系统自动生成]\n"
        "## 本轮已问过的题目（禁止重复）\n"
        + "\n".join(lines)
        + "\n\n规则：不要再出以上题目或类似题目的变体。每次出题必须是新的知识点方向。"
    )


def _fallback_coding_question(state: ChatState) -> str:
    candidates = (
        state.get("candidate_questions") or state.get("retrieved_questions") or []
    )
    coding_candidate = None
    for q in candidates:
        haystack = " ".join(
            str(q.get(k) or "") for k in ("question", "cat1", "cat2", "tags")
        )
        if re.search(
            r"(算法|代码|手撕|数据结构|链表|排序|二分)", haystack, re.I
        ):
            coding_candidate = q
            break
    if coding_candidate:
        state["selected_question"] = coding_candidate
        state["question_source"] = "bank"
        state["question_source_reason"] = "fallback_selected_coding_candidate"
        return (
            f"来写一道代码题：{coding_candidate.get('question', '')}\n\n"
            "请直接写代码，并说明你的数据结构选择、关键边界条件，以及时间和空间复杂度。"
        )
    state["question_source"] = state.get("question_source") or "generated"
    state["question_source_reason"] = "fallback_generated_coding_question"
    return (
        "好，来写一道代码题。请根据候选人的技术栈和之前的面试内容，"
        "选择一道合适的手撕题（不要重复之前问过的方向）。"
        "要求候选人写代码并说明设计思路。"
    )


def _ensure_final_answer_quality(text: str, state: ChatState) -> str:
    if _is_bare_coding_prompt(text, state):
        logger.warning(
            "ReAct trace: event=bare_coding_prompt_fallback conversation_id=%s",
            state.get("conversation_id"),
        )
        return _fallback_coding_question(state)
    return text


def _fallback_react_answer(state: ChatState, reason: str) -> str:
    """Return a safe interviewer turn when ReAct/tool/final generation fails."""
    candidates = (
        state.get("candidate_questions") or state.get("retrieved_questions") or []
    )
    if candidates:
        selected = candidates[0]
        state["selected_question"] = selected
        state["question_source"] = state.get("question_source") or "search"
        state["question_source_reason"] = f"fallback_after_{reason}"
        return (
            f"我们先收束到一道具体题：{selected.get('question', '')}\n\n"
            "你不用展开太泛，直接说核心思路、关键取舍，以及你会怎么验证这个方案。"
        )

    state["question_source"] = "conversation"
    state["question_source_reason"] = f"fallback_after_{reason}"
    keywords = state.get("keywords") or []
    topic = "、".join(keywords[:3]) if keywords else "你刚才提到的项目"
    return (
        f"我们先围绕「{topic}」继续追问。请你挑一个最核心的模块，"
        "说明它的输入输出、关键流程、主要取舍，以及你是怎么验证效果的。"
    )


def _last_assistant_message(state: ChatState) -> str:
    for msg in reversed(state.get("message_history", []) or []):
        if msg.get("role") == "assistant":
            return str(msg.get("content") or "")
    return ""


# ── Repetitive question protection ────────────────────────

_MAX_CONSECUTIVE_SAME_QUESTION = 2


def _count_consecutive_similar_questions(state: ChatState) -> tuple[int, str]:
    """Count how many consecutive assistant messages are about the same core topic.

    Returns (count, topic_tokens_summary).  A "consecutive run" resets when
    the latest assistant message has significantly different core tokens from
    the previous one.

    Uses a lightweight token-overlap heuristic: extract Chinese spans/English
    words from each assistant message, compute overlap coefficient between
    consecutive pairs, and count the streak where overlap >= 0.15.
    """
    messages = state.get("message_history", []) or []
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    if len(assistant_msgs) < 2:
        return 0, ""

    def _core_tokens(text: str) -> set[str]:
        tokens = set()
        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{2,}", text.lower()):
            tokens.add(t)
        for t in re.findall(r"[\u4e00-\u9fff]{2,4}", text):
            tokens.add(t)
        # Remove generic filler tokens that inflate similarity
        _fillers = {
            "请",
            "问题",
            "回答",
            "面试",
            "一下",
            "具体",
            "详细",
            "介绍一下",
            "说说",
        }
        return tokens - _fillers

    recent_assistants = assistant_msgs[-6:]  # look at last 6 assistant messages
    token_sets = [_core_tokens(m.get("content", "")) for m in recent_assistants]

    # Walk backwards counting consecutive similar pairs
    # Use overlap coefficient: |A∩B| / min(|A|,|B|) — better than Jaccard
    # for detecting repetition when one message is much longer than the other.
    count = 0
    for i in range(len(token_sets) - 1, 0, -1):
        curr, prev = token_sets[i], token_sets[i - 1]
        if not curr or not prev:
            break
        intersection = curr & prev
        overlap = len(intersection) / max(min(len(curr), len(prev)), 1)
        if overlap >= 0.15:
            count += 1
        else:
            break

    # Return the topic summary of the most recent assistant message
    last_tokens = token_sets[-1] if token_sets else set()
    return count, "、".join(sorted(last_tokens)[:5])


def _build_repetition_protection_note(state: ChatState) -> str:
    """If the interviewer has been asking about the same topic too many times
    consecutively, return a hard constraint note for the system prompt.

    Returns empty string when no protection is needed.
    """
    count, topic_summary = _count_consecutive_similar_questions(state)
    if count < _MAX_CONSECUTIVE_SAME_QUESTION:
        return ""

    logger.info(
        "ReAct trace: event=repetition_protection conversation_id=%s "
        "consecutive_count=%s topic=%s",
        state.get("conversation_id"),
        count,
        topic_summary,
    )

    return (
        "## ⚠️ 节奏保护（硬约束）\n"
        f"你已经连续 {count + 1} 次围绕同一话题「{topic_summary}」追问。\n"
        "- 不要再用同样的方式施压（如反复要求「写出来」「直接回答」）。\n"
        "- 必须做以下三选一：\n"
        "  1) 给一个简短提示/思路引导，让候选人自己想；\n"
        "  2) 记录为候选人的薄弱点，然后切换到下一个考察方向；\n"
        "  3) 降低难度，换个更基础的角度考察同一知识点。\n"
        "- 禁止原样重复上一题的施压话术。\n"
    )


def _looks_like_candidate_question(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped.endswith(("?", "？")):
        return True
    return bool(re.search(r"(想问|请问|了解一下|团队|实习生|培养|业务|落地)", stripped))


async def _forced_closing_response(state: ChatState) -> str:
    """Hard-stop overlong interviews so ReAct cannot drift back to tech rounds.

    Now generates a structured LLM-based summary instead of hardcoded text.
    """
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


def _basis_event_payload(meta: dict) -> dict:
    return {
        "basis_type": meta.get("basis_type"),
        "basis_question_ids": meta.get("basis_question_ids", []),
        "basis_confidence": meta.get("basis_confidence", 0.0),
        "should_show_references": meta.get("should_show_references", False),
        "selected_basis_questions": meta.get("selected_basis_questions", []),
        "resume_ref": meta.get("resume_ref", ""),
        "jd_ref": meta.get("jd_ref", ""),
    }


def _trace_safe_value(value):
    """Keep ReAct trace fields compact and free of arbitrary payloads."""
    if isinstance(value, str):
        return value[:_TRACE_STRING_LIMIT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_trace_safe_value(v) for v in list(value)[:_TRACE_LIST_LIMIT]]
    if isinstance(value, dict):
        return {
            str(k)[:40]: _trace_safe_value(v)
            for k, v in list(value.items())[:_TRACE_LIST_LIMIT]
        }
    return str(type(value).__name__)


def _sanitize_tool_args(tool_call: dict) -> dict:
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    try:
        args = json.loads(raw_args or "{}")
    except (TypeError, json.JSONDecodeError):
        return {"_parse_error": "invalid_json"}

    if not isinstance(args, dict):
        return {"_shape": type(args).__name__}

    sanitized = {}
    for key, value in args.items():
        if key in _SAFE_TOOL_ARG_KEYS:
            sanitized[key] = _trace_safe_value(value)
        else:
            sanitized[key] = "<redacted>"
    return sanitized


def _summarize_tool_output(tool_name: str, output: str, state: ChatState) -> dict:
    summary: dict[str, object] = {"ok": True}
    try:
        parsed = json.loads(output or "null")
    except (TypeError, json.JSONDecodeError):
        parsed = None
        summary["ok"] = False
        summary["error"] = "invalid_json_output"

    if isinstance(parsed, dict) and parsed.get("error"):
        summary["ok"] = False
        summary["error"] = str(parsed["error"])[:_TRACE_STRING_LIMIT]

    if tool_name == "load_skill":
        summary["active_skills"] = list(state.get("active_skills", []))
        return summary

    if tool_name in {"search_questions", "draw_questions"}:
        results = (
            [] if not summary["ok"] else state.get("retrieved_questions", []) or []
        )
        summary["result_count"] = len(results)
        summary["result_ids"] = [
            q.get("id")
            for q in results[:_TRACE_LIST_LIMIT]
            if isinstance(q, dict) and q.get("id") is not None
        ]
        return summary

    if parsed is not None:
        summary["output_type"] = type(parsed).__name__
    return summary


def _log_react_llm_step(
    state: ChatState,
    *,
    react_step: int,
    finish_reason: str | None,
    tool_count: int,
    elapsed_ms: int,
) -> None:
    logger.info(
        "ReAct trace: event=llm_step conversation_id=%s react_step=%s "
        "finish_reason=%s tool_count=%s elapsed_ms=%s",
        state.get("conversation_id"),
        react_step,
        finish_reason,
        tool_count,
        elapsed_ms,
    )


def _log_react_tool_call(
    state: ChatState,
    *,
    react_step: int,
    tool_name: str,
    args: dict,
    result: dict,
    elapsed_ms: int,
) -> None:
    logger.info(
        "ReAct trace: event=tool_call conversation_id=%s react_step=%s "
        "tool_name=%s args=%s result=%s elapsed_ms=%s",
        state.get("conversation_id"),
        react_step,
        tool_name,
        args,
        result,
        elapsed_ms,
    )


def _normalize_react_marker(text: str) -> str:
    return text.strip().strip("`'\"“”‘’").lower()


def _is_internal_react_marker(text: str) -> bool:
    normalized = _normalize_react_marker(text)
    if not normalized:
        return False
    return normalized in _INTERNAL_REACT_MARKERS


def _fallback_interviewer_response(marker: str, state: ChatState) -> str:
    """Replace leaked internal markers with a safe interviewer turn."""
    normalized = _normalize_react_marker(marker)
    logger.warning(
        "ReAct trace: event=internal_marker_filtered conversation_id=%s marker=%s",
        state.get("conversation_id"),
        normalized[:_TRACE_STRING_LIMIT],
    )

    if normalized == "project-deep-dive":
        return (
            "我们继续围绕你的项目做深挖。你刚才提到“AI 追问编排”和“题库/JD 匹配”，"
            "请具体讲一下：一次候选人回答进入后端后，从意图判断、关键词提取、题库检索到生成追问，"
            "完整链路是怎么设计的？中间你做过哪些取舍？"
        )

    if normalized == "algorithm-coding":
        return (
            "我们切到算法面试。我会先从基础思路开始考察：请你口述一下两数之和这类题的解法，"
            "包括数据结构选择、时间复杂度和边界情况。"
        )

    return (
        "我继续追问一个具体问题：请结合你刚才的项目，说明其中一个核心模块的设计方案、"
        "关键取舍，以及你如何验证它确实解决了问题。"
    )


async def _regenerate_after_dup(
    messages: list[dict],
    state: ChatState,
) -> AsyncGenerator[dict, None]:
    """Re-stream after a duplicate output was detected.

    Called once when OutputDeduplicator flags 'exact' or 'similar'.  Streams
    the regenerated answer directly — no second dedup check (one retry only).
    """
    async for event in stream_llm_messages(
        messages,
        user_id=state["user_id"],
        model=state.get("model"),
        yield_thinking=False,
    ):
        if isinstance(event, dict):
            if event.get("type") == "content":
                yield {"type": "chunk", "content": event.get("content", "")}
        else:
            yield {"type": "chunk", "content": event}


async def _stream_final_answer(
    messages: list[dict],
    state: ChatState,
) -> AsyncGenerator[dict, None]:
    """Stream final answer while guarding against internal ReAct marker leakage.

    Integrates two-level output dedup (hash + Jaccard) to detect and regenerate
    repeated responses before they reach the user.
    """
    chunks: list[str] = []

    # Track thinking lifecycle for synthesizing thinking_done
    is_thinking = False
    thinking_start_time = None
    thinking_content = ""

    async for event in stream_llm_messages(
        messages,
        user_id=state["user_id"],
        model=state.get("model"),
        yield_thinking=True,
    ):
        if isinstance(event, dict):
            event_type = event.get("type")
            content = event.get("content", "")

            if event_type == "thinking_start":
                is_thinking = True
                thinking_start_time = time.time()
                _emit({"type": "thinking_start", "content": ""})
            elif event_type == "thinking":
                thinking_content += content
                _emit({"type": "thinking", "content": content})
            elif event_type == "content":
                if is_thinking:
                    is_thinking = False
                    duration = (
                        round(time.time() - thinking_start_time, 1)
                        if thinking_start_time
                        else 0
                    )
                    _emit({
                        "type": "thinking_done",
                        "duration": duration,
                        "content": thinking_content,
                    })
                chunks.append(content)
        else:
            chunks.append(event)

    # Handle case where stream ended while still in thinking mode
    if is_thinking:
        duration = (
            round(time.time() - thinking_start_time, 1) if thinking_start_time else 0
        )
        _emit({
            "type": "thinking_done",
            "duration": duration,
            "content": thinking_content,
        })

    final_text = "".join(chunks)
    if _is_internal_react_marker(final_text):
        final_text = _fallback_interviewer_response(final_text, state)
    final_text = _ensure_final_answer_quality(final_text, state)

    # Two-level output dedup: check before yielding
    if final_text:
        deduplicator = state.setdefault("output_deduplicator", OutputDeduplicator())
        dup_result = deduplicator.check(final_text)

        if dup_result == "exact":
            logger.info(
                "ReAct trace: event=output_dedup_exact conversation_id=%s",
                state.get("conversation_id"),
            )
            # Inject note and regenerate once
            messages.append({
                "role": "user",
                "content": "【系统提示】你刚才的回答和之前的完全相同，请换一个角度或切换话题。",
            })
            async for event in _regenerate_after_dup(messages, state):
                yield event
            return
        elif dup_result == "similar":
            logger.info(
                "ReAct trace: event=output_dedup_similar conversation_id=%s",
                state.get("conversation_id"),
            )
            # Inject note and regenerate once
            messages.append({
                "role": "user",
                "content": "【系统提示】你刚才的回答和之前的高度相似，请用不同的话术重新回答。",
            })
            async for event in _regenerate_after_dup(messages, state):
                yield event
            return
        else:
            deduplicator.record(final_text)

    if final_text:
        yield {"type": "chunk", "content": final_text}


def _final_answer_events_from_text(
    final_text: str,
    state: ChatState,
) -> list[dict]:
    """Convert pre-captured LLM answer text into yieldable events.

    Note: dedup for the direct-answer path is handled by _react_loop
    (which has access to messages for regeneration).
    """
    if _is_internal_react_marker(final_text):
        final_text = _fallback_interviewer_response(final_text, state)
    final_text = _ensure_final_answer_quality(final_text, state)
    if not final_text:
        return []
    return [{"type": "chunk", "content": final_text}]


def _build_react_metadata(state: ChatState, response_text: str) -> tuple[dict, str]:
    """Build done-event metadata from the final streamed response.

    Reuses the existing basis parsing contract so the router can keep emitting
    the same SSE shape as the previous pipeline.
    """
    from app.agents.chat.nodes import (
        _extract_company_from_sources,
        _extract_round_from_sources,
        _filter_basis_ids_by_response,
        _get_jd_title,
        _get_resume_name,
        _parse_basis_from_response,
        _response_references_jd,
        _response_references_resume,
        validate_basis,
    )

    parsed = _parse_basis_from_response(response_text)
    clean_response = parsed.get("clean_response", response_text)
    retrieved = state.get("retrieved_questions", []) or []
    candidates = state.get("candidate_questions") or retrieved
    retrieved_ids = {q.get("id") for q in retrieved if q.get("id")}

    basis = validate_basis(parsed, retrieved_ids)
    if basis.get("should_show_references") and basis.get("basis_question_ids"):
        aligned_basis_ids = _filter_basis_ids_by_response(
            clean_response, basis["basis_question_ids"], retrieved
        )
        if len(aligned_basis_ids) != len(basis["basis_question_ids"]):
            logger.info(
                "ReAct basis alignment filtered ids: "
                f"before={basis['basis_question_ids']}, after={aligned_basis_ids}"
            )
        basis["basis_question_ids"] = aligned_basis_ids
        basis["should_show_references"] = bool(aligned_basis_ids)
        if not aligned_basis_ids:
            basis["basis_confidence"] = min(basis["basis_confidence"], 0.3)

    metadata: dict[str, object] = {
        "basis_type": basis["basis_type"],
        "basis_question_ids": basis["basis_question_ids"],
        "basis_confidence": basis["basis_confidence"],
        "should_show_references": basis["should_show_references"],
        "active_skills": state.get("active_skills", []),
        "asked_question_text": clean_response,
    }

    if retrieved:
        metadata["retrieved_questions"] = [
            {
                "id": q.get("id"),
                "question": q.get("question", ""),
                "cat1": q.get("cat1", ""),
                "company": _extract_company_from_sources(q),
                "round": _extract_round_from_sources(q),
            }
            for q in retrieved[:3]
        ]

    if basis["basis_question_ids"]:
        basis_id_set = set(basis["basis_question_ids"])
        basis_qs = [q for q in retrieved if q.get("id") in basis_id_set]
        if not basis_qs:
            try:
                from app.db.connection import get_db_connection

                with get_db_connection() as conn:
                    placeholders = ",".join("?" * len(basis["basis_question_ids"]))
                    rows = conn.execute(
                        f"SELECT id, question, cat1, cat2 FROM question_bank "
                        f"WHERE id IN ({placeholders}) AND deleted_at IS NULL AND status = 'approved'",
                        basis["basis_question_ids"],
                    ).fetchall()
                    basis_qs = [
                        {
                            "id": r[0],
                            "question": r[1],
                            "cat1": r[2],
                            "cat2": r[3],
                        }
                        for r in rows
                    ]
            except Exception as e:
                logger.debug(f"ReAct basis DB fallback failed: {e}")

        metadata["selected_basis_questions"] = [
            {
                "id": q.get("id"),
                "question": q.get("question", ""),
                "cat1": q.get("cat1", ""),
                "company": _extract_company_from_sources(q),
                "round": _extract_round_from_sources(q),
            }
            for q in basis_qs
        ]

    selected_question, selected_reason = _infer_selected_question(
        clean_response,
        basis["basis_question_ids"],
        candidates,
    )
    if not selected_question and state.get("selected_question"):
        selected_question = state.get("selected_question")
        selected_reason = (
            state.get("question_source_reason") or "state_selected_question"
        )

    if selected_question:
        state["selected_question"] = selected_question
        metadata["selected_question"] = _public_question(selected_question)
        metadata["question_source"] = state.get("question_source") or "search"
        metadata["question_source_reason"] = selected_reason
    else:
        source = state.get("question_source")
        metadata["selected_question"] = None
        metadata["question_source"] = (
            "conversation"
            if source in {"search", "draw"}
            else (source or "conversation")
        )
        metadata["question_source_reason"] = (
            state.get("question_source_reason")
            if source not in {"search", "draw"}
            else "candidate_questions_not_explicitly_used"
        )

    if candidates:
        metadata["candidate_questions"] = [
            _public_question(q)
            for q in candidates[:3]
            if _public_question(q) is not None
        ]

    if state.get("resume_summary") and _response_references_resume(
        clean_response, state["resume_summary"]
    ):
        metadata["resume_ref"] = _get_resume_name(state["user_id"])

    if state.get("jd_text") and _response_references_jd(
        clean_response, state["jd_text"]
    ):
        metadata["jd_ref"] = _get_jd_title(state.get("jd_id"))

    return metadata, clean_response


def _initial_state(
    conversation_id: str,
    user_id: int,
    user_message: str,
    mode: str,
    jd_id: int | None,
    resume_text: str | None,
    jd_text: str | None,
    model: str | None,
    bank_mode: str | None,
) -> ChatState:
    return {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "user_message": user_message,
        "mode": mode,
        "jd_id": jd_id,
        "jd_text": jd_text,
        "resume_text": resume_text,
        "model": model,
        "bank_mode": bank_mode or "public",
        "memories": [],
        "memory_summaries": [],
        "resume_summary": None,
        "session_notes": "",
        "message_history": [],
        "compressed_context": None,
        "recent_messages": [],
        "budget_snapshot": None,
        "interview_context": "",
        "job_position": None,
        "intent": "interview_question",
        "keywords": [],
        "search_query": "",
        "retrieval_intent": None,
        "search_positive_terms": [],
        "search_negative_terms": [],
        "question_type": None,
        "answer_complete": False,
        "retrieved_questions": [],
        "candidate_questions": [],
        "selected_question": None,
        "question_source": None,
        "question_source_reason": None,
        "selected_basis_questions": [],
        "rerank_metadata": {},
        "response": "",
        "metadata": {},
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "active_skills": [],
    }


# ═══════════════════════════════════════════════════
#  Pipeline Steps
# ═══════════════════════════════════════════════════


async def _step_load_context(state: ChatState) -> ChatState:
    """加载上下文：历史、记忆、简历、session notes"""
    _step("loading", "正在加载对话历史...", reason=STEP_REASONS["loading"])
    memory_result, history_result = await asyncio.gather(
        recall_memories(state),
        load_history(state),
    )
    state.update(memory_result)
    state.update(history_result)
    state["session_notes"] = chat_service.get_session_notes(state["conversation_id"])

    # 恢复上一轮持久化的 active skill names
    conversation_metadata = await asyncio.to_thread(
        chat_service.get_conversation_metadata,
        state["conversation_id"],
    )
    from app.agents.chat.nodes import _restore_active_skills_from_metadata

    _restore_active_skills_from_metadata(state, conversation_metadata)

    _step("context", "正在加载个人画像...", reason=STEP_REASONS["context"])
    interview_context, job_position = build_interview_context(
        state["user_id"], conversation_id=state["conversation_id"]
    )
    state["interview_context"] = interview_context
    state["job_position"] = job_position

    # 上下文压缩
    result = await summarize_context(state)
    state.update(result)

    # 检查轮次限制
    from app.agents.chat.nodes import check_round_limit

    if not check_round_limit(state.get("message_history", [])):
        raise RuntimeError("对话已达最大轮次限制（50轮），请新建对话继续")

    return state


async def _step_classify(state: ChatState) -> ChatState:
    """意图分类 + 关键词提取 + 记忆召回（单次 LLM 调用）"""
    recent = state.get("recent_messages", [])
    recent_context = ""
    if recent:
        recent_context = "\n".join(
            f"{'面试官' if m['role'] == 'assistant' else '候选人'}: {m['content'][:100]}"
            for m in recent[-4:]
        )

    is_first_message = len(state.get("message_history", [])) <= 1
    if is_first_message:
        _step("understanding", "正在理解你的问题...", reason=STEP_REASONS["understanding_first"])
        (
            intent,
            memory_ids,
            keywords,
            search_query,
            answer_complete,
            structured_rewrite,
        ) = await classify_and_recall_fast(
            user_message=state["user_message"],
            memory_summaries=state.get("memory_summaries", []),
            recent_context=recent_context,
        )
    else:
        _step("understanding", "正在分析你的回答...", reason=STEP_REASONS["understanding_follow"])
        (
            intent,
            memory_ids,
            keywords,
            search_query,
            answer_complete,
            structured_rewrite,
        ) = await classify_and_recall(
            user_message=state["user_message"],
            recent_context=recent_context,
            memory_summaries=state.get("memory_summaries", []),
            user_id=state["user_id"],
        )

    state["intent"] = intent
    state["keywords"] = keywords
    state["search_query"] = search_query
    state["answer_complete"] = answer_complete

    if structured_rewrite:
        state["retrieval_intent"] = structured_rewrite.get("retrieval_intent")
        state["search_positive_terms"] = structured_rewrite.get("positive_terms", [])
        state["search_negative_terms"] = structured_rewrite.get("negative_terms", [])
        state["question_type"] = structured_rewrite.get("question_type")

    if memory_ids:
        full_memories = await asyncio.to_thread(
            chat_service.get_memories_by_ids, memory_ids, state["user_id"]
        )
        state["memory_summaries"] = [
            {
                "id": m["id"],
                "memory_type": m["memory_type"],
                "summary": m["content"][:80],
                "updated_at": m["created_at"],
            }
            for m in full_memories
        ]
    else:
        state["memory_summaries"] = chat_service.get_memory_summaries(
            state["user_id"], limit=3
        )

    if intent == "interview_question" and keywords:
        topic_tag = ", ".join(keywords[:3])
        pre_note = f"[pending] 候选人正在回答: {topic_tag}"
        current_notes = state.get("session_notes", "")
        state["session_notes"] = (
            f"{current_notes}\n{pre_note}" if current_notes else pre_note
        )

    logger.info(
        f"Pipeline classify: intent={intent}, keywords={keywords}, "
        f"search_query='{search_query}', answer_complete={answer_complete}"
    )
    return state


async def _step_extract_memory(state: ChatState) -> None:
    """后台提取记忆（不阻塞主流程）"""
    try:
        await extract_memory(state)
    except Exception as e:
        logger.debug(f"后台记忆提取失败（不影响主流程）: {e}")


# ═══════════════════════════════════════════════════
#  ReAct Loop (core autonomous tool-calling loop)
# ═══════════════════════════════════════════════════

MAX_REACT_STEPS = 5


async def _persist_active_skills(state: ChatState) -> None:
    """Persist only cross-turn skills to conversation metadata.

    Mode skills such as algorithm-coding/project-deep-dive are turn-scoped; if
    they are persisted, the next unrelated turn can inherit the wrong mode.
    """
    try:
        conversation_id = state.get("conversation_id")
        if not conversation_id:
            return
        active_skills = [
            name
            for name in state.get("active_skills", [])
            if name in _PERSISTENT_SKILLS
        ]
        await asyncio.to_thread(
            chat_service.update_conversation_metadata,
            conversation_id,
            {
                "persistent_skill_names": active_skills,
                "active_skill_names": active_skills,
                "last_turn_skills": state.get("active_skills", []),
            },
        )
    except Exception:
        logger.exception("Failed to persist active_skills")


async def _react_loop(state: ChatState) -> AsyncGenerator[dict, None]:
    """ReAct loop: LLM autonomously selects tools, then streams final answer.

    Flow:
    1. Build system prompt (with skill catalog + tool guidance)
    2. Build messages
    3. ReAct loop: LLM calls tools or answers directly
    4. Stream final answer
    """
    forced_closing = await _forced_closing_response(state)
    if forced_closing:
        _emit({"type": "step", "step": "closing", "message": "正在收尾面试...", "reason": STEP_REASONS["closing"]})
        yield {"type": "chunk", "content": forced_closing}
        yield {"type": "done"}
        return

    # 1. Build system prompt
    system_prompt = build_react_system_prompt(state)
    state["active_skill_instructions"] = []  # consumed; skills baked into system prompt

    # 1.5 Inject repetition protection if needed
    repetition_note = _build_repetition_protection_note(state)
    if repetition_note:
        system_prompt += f"\n\n{repetition_note}"

    # 2. Build messages
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Compressed context
    compressed = state.get("compressed_context")
    if compressed:
        messages.append({"role": "user", "content": f"[以下是更早对话的压缩摘要，由系统生成，不是候选人的话]\n{compressed}"})

    # Recent messages
    for msg in state.get("recent_messages", [])[-10:]:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": msg.get("content", "")})

    # Inject PREVIOUSLY ASKED as dynamic user message (not in cached system prompt)
    asked_section = _build_previously_asked_section(state)
    if asked_section:
        messages.append({"role": "user", "content": asked_section})

    # Current user message
    messages.append({"role": "user", "content": state["user_message"]})

    # 3. ReAct loop
    react_started = time.monotonic()
    tool_call_count = 0
    seen_tool_calls: set[str] = set()
    stop_reason = ""
    final_answer_text = ""
    for step in range(REACT_BUDGET.max_steps):
        react_step = step + 1
        # Budget checks
        if tool_call_count >= REACT_BUDGET.max_tool_calls:
            stop_reason = "max_tool_calls"
            break
        if time.monotonic() - react_started > REACT_BUDGET.max_seconds:
            stop_reason = "max_seconds"
            break
        # Rebuild system prompt if skills were loaded in previous step
        if step > 0 and state.get("active_skill_instructions"):
            system_prompt = build_react_system_prompt(state)
            if repetition_note:
                system_prompt += f"\n\n{repetition_note}"
            messages[0] = {"role": "system", "content": system_prompt}
            state["active_skill_instructions"] = []  # consumed
        llm_started = time.monotonic()
        try:
            result = await llm_with_tools(
                messages,
                ALL_TOOLS,
                user_id=state["user_id"],
                model=state.get("model"),
            )
        except Exception as e:
            logger.error(f"ReAct step {step} LLM call failed: {e}")
            break

        tool_calls = result.get("tool_calls") or []
        _log_react_llm_step(
            state,
            react_step=react_step,
            finish_reason=result.get("finish_reason"),
            tool_count=len(tool_calls),
            elapsed_ms=int((time.monotonic() - llm_started) * 1000),
        )

        if not tool_calls:
            content = result.get("content")
            if isinstance(content, str) and content.strip():
                final_answer_text = content
            break  # LLM decided to answer directly

        # Append assistant message with tool_calls
        messages.append(
            {
                "role": "assistant",
                "content": result.get("content"),
                "tool_calls": tool_calls,
            }
        )

        # Execute each tool call
        for tc in tool_calls:
            # Validate before execution
            try:
                tc = validate_tool_call(tc)
            except StopRun as exc:
                stop_reason = exc.reason
                logger.warning(
                    "ReAct trace: event=validation_failed conversation_id=%s "
                    "react_step=%s reason=%s",
                    state.get("conversation_id"),
                    react_step,
                    exc.reason,
                )
                messages.append(
                    make_tool_result_message(
                        tc.get("id", "invalid"),
                        json.dumps({"error": exc.reason}),
                    )
                )
                break  # break inner loop, outer loop will check stop_reason

            # Loop detection
            try:
                sig_args = tc["function"]["arguments"]
                if isinstance(sig_args, str):
                    sig_args = json.loads(sig_args)
                call_sig = f"{tc['function']['name']}:{json.dumps(sig_args, sort_keys=True, ensure_ascii=False)}"
            except (json.JSONDecodeError, TypeError, KeyError):
                call_sig = f"{tc.get('function', {}).get('name', '?')}:unparseable"
            if call_sig in seen_tool_calls:
                stop_reason = "loop_detected"
                logger.warning(
                    "ReAct trace: event=loop_detected conversation_id=%s "
                    "react_step=%s tool=%s",
                    state.get("conversation_id"),
                    react_step,
                    tc["function"]["name"],
                )
                messages.append(
                    make_tool_result_message(
                        tc.get("id", "loop"),
                        json.dumps(
                            {
                                "error": "loop_detected",
                                "message": "Same tool call repeated — stopping.",
                            }
                        ),
                    )
                )
                break
            seen_tool_calls.add(call_sig)

            tool_call_count += 1

            tool_name = tc["function"]["name"]
            tool_args = _sanitize_tool_args(tc)

            # Emit progress
            _emit(
                {
                    "type": "step",
                    "step": tool_name,
                    "message": tool_progress_message(tc),
                    "reason": STEP_REASONS.get(tool_name, ""),
                }
            )

            # Execute tool
            tool_started = time.monotonic()
            output = await execute_tool(tc, state)
            _log_react_tool_call(
                state,
                react_step=react_step,
                tool_name=tool_name,
                args=tool_args,
                result=_summarize_tool_output(tool_name, output, state),
                elapsed_ms=int((time.monotonic() - tool_started) * 1000),
            )

            # Emit retrieved events for search/draw results
            if tool_name in (
                "search_questions",
                "draw_questions",
            ) and state.get("retrieved_questions"):
                _emit(
                    {
                        "type": "retrieved",
                        "questions": [
                            {
                                "id": q.get("id"),
                                "question": q.get("question", ""),
                                "cat1": q.get("cat1", ""),
                                "cat2": q.get("cat2", ""),
                                "company": _extract_company(q),
                                "round": _extract_round(q),
                            }
                            for q in state["retrieved_questions"][:3]
                        ],
                    }
                )

            # Emit insight events for user-visible decision points
            if tool_name == "load_skill":
                skill_label = (
                    tool_progress_message(tc).replace("正在加载", "").replace("...", "")
                )
                _emit({"type": "insight", "text": f"切换到{skill_label}模式"})
            elif tool_name in ("search_questions", "draw_questions") and state.get(
                "retrieved_questions"
            ):
                top_q = (
                    state["retrieved_questions"][0]
                    if state["retrieved_questions"]
                    else None
                )
                if top_q:
                    topic = top_q.get("cat2") or top_q.get("cat1") or "相关技术"
                    _emit(
                        {
                            "type": "insight",
                            "text": f"从题库检索到关于「{topic}」的题目",
                        }
                    )

            # 3d: Pre-prune search/draw tool output to top 3 before appending to messages.
            # Full results remain in state["retrieved_questions"] for downstream use.
            msg_output = output
            if tool_name in ("search_questions", "draw_questions"):
                try:
                    parsed_out = json.loads(output)
                    if isinstance(parsed_out, list) and len(parsed_out) > 3:
                        msg_output = json.dumps(parsed_out[:3], ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass
            messages.append(make_tool_result_message(tc["id"], msg_output))

        # If inner loop broke due to validation failure or loop detection, exit outer loop
        if stop_reason:
            break

        # 3d: Prune old tool results (>5 turns ago) to a 1-line summary.
        # Keeps context lean without losing the fact that a tool was called.
        _msg_end = len(messages)
        for _mi, _msg in enumerate(messages):
            if _msg.get("role") == "tool" and (_msg_end - _mi) > 5:
                _msg["content"] = "[已裁剪的工具输出]"

        if react_step == REACT_BUDGET.max_steps:
            stop_reason = "max_steps"

    # Log stop reason
    if stop_reason:
        logger.warning(
            "ReAct trace: event=stopped conversation_id=%s reason=%s "
            "steps=%s tool_calls=%s elapsed_ms=%s",
            state.get("conversation_id"),
            stop_reason,
            react_step,
            tool_call_count,
            int((time.monotonic() - react_started) * 1000),
        )

    # 4. Stream final answer
    _emit({"type": "step", "step": "generating", "message": "正在生成回答...", "reason": STEP_REASONS["generating"]})
    try:
        if stop_reason == "max_seconds":
            yield {
                "type": "chunk",
                "content": _fallback_react_answer(state, stop_reason),
            }
        elif final_answer_text:
            # Check output dedup for direct-answer path
            final_text_clean = _ensure_final_answer_quality(
                _fallback_interviewer_response(final_answer_text, state)
                if _is_internal_react_marker(final_answer_text)
                else final_answer_text,
                state,
            )
            deduplicator = state.setdefault("output_deduplicator", OutputDeduplicator())
            dup_result = deduplicator.check(final_text_clean) if final_text_clean else "ok"

            if dup_result == "exact":
                logger.info(
                    "ReAct trace: event=output_dedup_exact conversation_id=%s",
                    state.get("conversation_id"),
                )
                messages.append({
                    "role": "user",
                    "content": "【系统提示】你刚才的回答和之前的完全相同，请换一个角度或切换话题。",
                })
                async for event in _stream_final_answer(messages, state):
                    yield event
            elif dup_result == "similar":
                logger.info(
                    "ReAct trace: event=output_dedup_similar conversation_id=%s",
                    state.get("conversation_id"),
                )
                messages.append({
                    "role": "user",
                    "content": "【系统提示】你刚才的回答和之前的高度相似，请用不同的话术重新回答。",
                })
                async for event in _stream_final_answer(messages, state):
                    yield event
            else:
                if final_text_clean:
                    deduplicator.record(final_text_clean)
                for event in _final_answer_events_from_text(final_answer_text, state):
                    yield event
        else:
            async for event in _stream_final_answer(messages, state):
                yield event
    except Exception as e:
        logger.exception(
            "ReAct trace: event=final_answer_failed conversation_id=%s reason=%s",
            state.get("conversation_id"),
            type(e).__name__,
        )
        yield {
            "type": "chunk",
            "content": _fallback_react_answer(state, type(e).__name__),
        }

    yield {"type": "done"}


# ═══════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════


async def run_chat(
    conversation_id: str,
    user_id: int,
    user_message: str,
    mode: str = "free_practice",
    jd_id: int = None,
    resume_text: str = None,
    jd_text: str = None,
    model: str = None,
    bank_mode: str = None,
) -> AsyncGenerator[dict, None]:
    """面试对话 pipeline — SSE 兼容的 async generator。

    替代 LangGraph StateGraph，使用纯 async pipeline。
    所有事件通过 _event_queue_var 上下文变量传递。
    """
    queue: asyncio.Queue = asyncio.Queue()
    token = _event_queue_var.set(queue)

    state = _initial_state(
        conversation_id,
        user_id,
        user_message,
        mode,
        jd_id,
        resume_text,
        jd_text,
        model,
        bank_mode,
    )

    async def _run_pipeline() -> None:
        t0 = time.monotonic()
        try:
            # 1. 加载上下文
            await _step_load_context(state)

            # 2. 意图分类 + 关键词
            await _step_classify(state)

            # 3-5. ReAct 循环（替代 resolve_skills + route_and_generate）
            response = ""
            metadata = {}

            # Hard route: end_interview bypasses ReAct entirely — no tools
            if state.get("intent") == "end_interview":
                _emit(
                    {
                        "type": "step",
                        "step": "closing",
                        "message": "正在生成面试总结...",
                        "reason": STEP_REASONS["closing"],
                    }
                )
                closing_text = await _generate_end_interview_response(state)
                response = closing_text
                _emit({"type": "chunk", "content": closing_text})
                built_metadata, clean_response = _build_react_metadata(state, response)
                if built_metadata:
                    metadata = built_metadata
                response = clean_response
                _emit({"type": "basis", **_basis_event_payload(metadata)})
                _emit({"type": "done", "metadata": metadata})
            else:
                async for event in _react_loop(state):
                    event_type = event.get("type")
                    if event_type == "done":
                        metadata = event.get("metadata", {})
                        built_metadata, clean_response = _build_react_metadata(
                            state, response
                        )
                        if built_metadata:
                            metadata = {**built_metadata, **metadata}
                        response = clean_response
                        _emit({"type": "basis", **_basis_event_payload(metadata)})
                        _emit({"type": "done", "metadata": metadata})
                        continue
                    if event_type in {
                        "chunk",
                        "thinking",
                        "thinking_start",
                        "thinking_done",
                        "error",
                    }:
                        if event_type == "chunk":
                            response += event.get("content", "")
                        _emit(event)
            state["response"] = response
            state["metadata"] = metadata

            # Persist/clear cross-turn skills so turn-scoped modes do not stick.
            await _persist_active_skills(state)

            # 后台记忆提取
            asyncio.create_task(_step_extract_memory(dict(state)))

            elapsed = time.monotonic() - t0
            logger.info(
                f"Pipeline completed in {elapsed:.1f}s, "
                f"intent={state.get('intent')}, "
                f"active_skills={state.get('active_skills', [])}"
            )
        except Exception as e:
            logger.exception("Pipeline 执行失败")
            queue.put_nowait({"type": "error", "message": _sanitize_error_message(e)})
        finally:
            queue.put_nowait(_SENTINEL)

    graph_task = asyncio.create_task(_run_pipeline())

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            yield item
            await asyncio.sleep(0)
    finally:
        _event_queue_var.reset(token)
        if not graph_task.done():
            graph_task.cancel()

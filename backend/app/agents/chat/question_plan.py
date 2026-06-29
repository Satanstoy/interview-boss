"""Question plan management and repetition protection.

Split from pipeline.py — contains functions for managing question plans,
selecting candidates, detecting repetitive questions, and building
previously-asked sections.
"""

from __future__ import annotations

import logging
import re

from app.agents.chat.state import ChatState

logger = logging.getLogger("interview-boss")

_MAX_CONSECUTIVE_SAME_QUESTION = 2


def _tokenize_for_overlap(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}", lowered))
    tokens.update(re.findall(r"[一-鿿]{2,4}", lowered))
    return {t for t in tokens if len(t.strip()) >= 2}


def _normalize_question_text(text: str) -> str:
    return re.sub(
        r"[\s`'\"""''。？?！!，,、：:；;（）()【】\\[\\]{}<>《》]", "", text or ""
    ).lower()


def _should_create_question_plan(state: ChatState) -> bool:
    """Return True when this turn is expected to ask a new bank-backed question."""
    intent = state.get("intent")
    if intent == "practice_request":
        return True
    if intent == "interview_question" and state.get("answer_complete") is True:
        return True
    if state.get("question_type") == "algorithm_coding":
        return True
    user_message = str(state.get("user_message") or "")
    return bool(re.search(r"(出题|来一道|换题|随机|手撕|代码题)", user_message))


def _candidate_contains_negative_term(candidate: dict, negative_terms: list[str]) -> bool:
    if not negative_terms:
        return False
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    ).lower()
    return any(str(term or "").lower() in text for term in negative_terms if term)


def _is_algorithm_candidate(candidate: dict) -> bool:
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    )
    return bool(re.search(r"(算法|代码|手撕|数据结构|链表|排序|二分|LRU|lru)", text, re.I))


def _allowed_focus_from_question(question: dict) -> list[str]:
    focus: list[str] = []
    for field in ("cat2", "cat1", "tags"):
        value = str(question.get(field) or "").strip()
        if not value:
            continue
        for part in re.split(r"[,，、/\s]+", value):
            part = part.strip()
            if len(part) >= 2 and part not in focus:
                focus.append(part)
            if len(focus) >= 6:
                return focus
    for token in sorted(_tokenize_for_overlap(str(question.get("question") or "")))[:6]:
        if token not in focus:
            focus.append(token)
    return focus[:6]


def _select_question_for_plan(
    state: ChatState,
    candidates: list[dict],
) -> tuple[dict | None, str]:
    """Select one candidate for hard question-plan binding."""
    negative_terms = state.get("search_negative_terms", []) or []
    viable = [
        q
        for q in candidates
        if isinstance(q, dict)
        and q.get("id")
        and q.get("question")
        and not _candidate_contains_negative_term(q, negative_terms)
    ]
    if not viable:
        return None, "no_viable_candidate"

    if state.get("question_type") == "algorithm_coding":
        for candidate in viable:
            if _is_algorithm_candidate(candidate):
                return candidate, "algorithm_candidate_match"

    return viable[0], "top_ranked_candidate"


def _maybe_create_question_plan(state: ChatState) -> dict | None:
    """Create next_question_plan from current candidates when the turn needs a new question."""
    if not _should_create_question_plan(state):
        return None

    candidates = state.get("candidate_questions") or state.get("retrieved_questions") or []
    selected, selection_reason = _select_question_for_plan(state, candidates)
    if not selected:
        state["question_plan_reason"] = selection_reason
        return None

    plan = {
        "must_ask": True,
        "question_id": selected.get("id"),
        "question_text": str(selected.get("question") or ""),
        "basis_type": "drawn_question" if state.get("question_source") == "draw" else "interview_question",
        "source": state.get("question_source") or "search",
        "strategy": state.get("intent") or "new_question",
        "allowed_focus": _allowed_focus_from_question(selected),
        "forbidden_focus": state.get("search_negative_terms", []) or [],
        "selection_reason": selection_reason,
    }
    state["selected_question"] = selected
    state["next_question_plan"] = plan
    state["question_source_reason"] = "question_plan_bound"
    return plan


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
        for t in re.findall(r"[一-鿿]{2,4}", text):
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

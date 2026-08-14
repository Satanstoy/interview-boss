"""问题检索重排(节点内部) - 从 nodes.py 机械抽取。

职责:检索候选题的确定性重排 + LLM 重排(误合并检测、关键词重叠、置信度校准)。
纯内部辅助,被 nodes.generate_response 等调用。
"""
import logging
import os
from app.services.llm import _call_llm_with_retry, _extract_json
from app.agents.chat.state import ChatState
from app.agents.chat.prompts import LLM_RERANK_PROMPT

# 检索重排参数(从 nodes.py 抽取,保持常量一致)
RERANK_CANDIDATE_LIMIT = 15
RERANK_RETURN_LIMIT = 5

logger = logging.getLogger("interview-boss")


def _contains_negative_term(question: dict, negative_terms: list[str]) -> bool:
    if not negative_terms:
        return False
    text = " ".join(
        str(question.get(field) or "") for field in ("question", "cat1", "cat2", "tags")
    ).lower()
    return any(str(term).lower() in text for term in negative_terms if term)


def _keyword_overlap_score(question: dict, terms: list[str]) -> int:
    text = " ".join(
        str(question.get(field) or "") for field in ("question", "cat1", "cat2", "tags")
    ).lower()
    score = 0
    for term in terms or []:
        term = str(term or "").strip().lower()
        if len(term) >= 2 and term in text:
            score += 1
    return score


def _clamp_confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _format_rerank_candidates(candidates: list[dict]) -> str:
    lines = []
    for idx, q in enumerate(candidates[:RERANK_CANDIDATE_LIMIT], 1):
        lines.append(
            f"{idx}. id={q.get('id')} | cat={q.get('cat1', '')}/{q.get('cat2', '')} | "
            f"rrf={round(float(q.get('_rrf_score') or 0), 5)} | "
            f"h={q.get('_heuristic_score', 0)} | freq={q.get('frequency', '')} | "
            f"tags={q.get('tags', '')} | question={q.get('question', '')}"
        )
    return "\n".join(lines)


def _deterministic_rerank_result(
    candidates: list[dict],
    negative_terms: list[str],
    strategy: str,
    target_topic: str,
    search_query: str,
) -> dict:
    """Fast local rerank used by default to avoid an extra LLM round-trip."""
    terms = []
    terms.extend((search_query or "").split())
    terms.extend((target_topic or "").split())
    terms = [term for term in terms if len(str(term).strip()) >= 2]

    scored = []
    filtered_reasons = []
    for idx, candidate in enumerate(candidates):
        qid = candidate.get("id")
        if qid is None:
            continue
        if _contains_negative_term(candidate, negative_terms):
            filtered_reasons.append(f"negative_term:{qid}")
            continue

        overlap = _keyword_overlap_score(candidate, terms)
        rrf = float(candidate.get("_rrf_score") or 0.0)
        heuristic = float(candidate.get("_heuristic_score") or 0.0)
        frequency = float(candidate.get("frequency") or 0.0)
        cat_text = f"{candidate.get('cat1', '')} {candidate.get('cat2', '')}".lower()

        strategy_bonus = 0.0
        if strategy == "deep_dive" and any(
            token in cat_text for token in ("项目", "agent", "rag", "llm", "系统")
        ):
            strategy_bonus += 1.0
        elif strategy == "topic_shift":
            strategy_bonus += 0.4

        score = (
            overlap * 4.0
            + rrf * 100.0
            + min(heuristic, 50.0) / 10.0
            + min(frequency, 20.0) / 20.0
            + strategy_bonus
            - idx * 0.01
        )
        scored.append((score, overlap, int(qid), candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    ranked_questions = [item[3] for item in scored[:RERANK_RETURN_LIMIT]]
    ranked_ids = [int(q["id"]) for q in ranked_questions if q.get("id") is not None]

    selected_basis_ids = []
    if strategy != "clarification":
        for score, overlap, qid, _candidate in scored:
            if overlap > 0:
                selected_basis_ids.append(qid)
            if len(selected_basis_ids) >= 2:
                break

    if strategy == "clarification":
        confidence = 0.0
    elif selected_basis_ids:
        top_score = scored[0][0] if scored else 0.0
        confidence = 0.82 if top_score >= 4.0 else 0.68
    else:
        confidence = 0.35

    return {
        "ranked_question_ids": ranked_ids,
        "selected_basis_ids": selected_basis_ids,
        "ranked_questions": ranked_questions,
        "selected_basis_questions": [
            q for q in ranked_questions if q.get("id") in set(selected_basis_ids)
        ],
        "confidence": confidence,
        "should_show_references": bool(selected_basis_ids) and confidence >= 0.55,
        "reasoning_summary": "deterministic_rrf_overlap_rerank",
        "filtered_reasons": filtered_reasons,
    }


def _should_use_llm_rerank(state: ChatState, deterministic: dict) -> bool:
    """Gate expensive LLM rerank. Default is off for latency."""
    mode = os.getenv("CHAT_LLM_RERANK_MODE", "off").strip().lower()
    if mode in {"0", "false", "off", "disabled"}:
        return False
    if mode in {"1", "true", "always", "on"}:
        return True
    if mode != "auto":
        return False

    # Auto mode is intentionally conservative: only call LLM when local ranking
    # cannot find any aligned basis but the user explicitly asks to change topics.
    return (
        state.get("strategy") == "topic_shift"
        and not deterministic.get("selected_basis_ids")
        and len(state.get("retrieved_questions", [])) >= 8
    )


def validate_rerank_result(
    rerank: dict,
    candidates: list[dict],
    negative_terms: list[str],
    strategy: str,
    target_topic: str,
    search_query: str,
) -> dict:
    """硬校验 LLM rerank 输出，保证不编 ID、不选噪声 basis。"""
    candidate_map = {int(q["id"]): q for q in candidates if q.get("id") is not None}
    candidate_ids = set(candidate_map)
    filtered_reasons = []

    def valid_id_list(values) -> list[int]:
        result = []
        if not isinstance(values, list):
            return result
        for raw in values:
            try:
                qid = int(raw)
            except (TypeError, ValueError, OverflowError):
                filtered_reasons.append(f"invalid_id:{raw}")
                continue
            if qid not in candidate_ids:
                filtered_reasons.append(f"non_candidate:{qid}")
                continue
            if _contains_negative_term(candidate_map[qid], negative_terms):
                filtered_reasons.append(f"negative_term:{qid}")
                continue
            if qid not in result:
                result.append(qid)
        return result

    ranked_ids = valid_id_list(rerank.get("ranked_question_ids"))[:RERANK_RETURN_LIMIT]
    if not ranked_ids:
        ranked_ids = [
            int(q["id"])
            for q in candidates
            if q.get("id") is not None
            and not _contains_negative_term(q, negative_terms)
        ][:RERANK_RETURN_LIMIT]

    selected_basis_ids = valid_id_list(rerank.get("selected_basis_ids"))[:2]
    selected_basis_ids = [qid for qid in selected_basis_ids if qid in ranked_ids]

    confidence = _clamp_confidence(rerank.get("confidence", 0.0))
    should_show = bool(rerank.get("should_show_references", False))

    relevance_terms = []
    relevance_terms.extend((search_query or "").split())
    relevance_terms.extend((target_topic or "").split())
    if strategy == "deep_dive":
        strongly_related = [
            qid
            for qid in selected_basis_ids
            if _keyword_overlap_score(candidate_map[qid], relevance_terms) > 0
        ]
        if len(strongly_related) != len(selected_basis_ids):
            filtered = set(selected_basis_ids) - set(strongly_related)
            for qid in filtered:
                filtered_reasons.append(f"deep_dive_weak_basis:{qid}")
            selected_basis_ids = strongly_related
    elif strategy == "clarification":
        selected_basis_ids = []
        should_show = False

    if confidence < 0.55 or not selected_basis_ids:
        should_show = False

    ranked_questions = [
        candidate_map[qid] for qid in ranked_ids if qid in candidate_map
    ]
    selected_basis_questions = [
        candidate_map[qid] for qid in selected_basis_ids if qid in candidate_map
    ]

    return {
        "ranked_question_ids": ranked_ids,
        "selected_basis_ids": selected_basis_ids,
        "ranked_questions": ranked_questions,
        "selected_basis_questions": selected_basis_questions,
        "confidence": confidence,
        "should_show_references": should_show,
        "reasoning_summary": str(rerank.get("reasoning_summary", ""))[:500],
        "filtered_reasons": filtered_reasons,
    }


async def llm_rerank_questions(state: ChatState) -> dict:
    """RRF 后重排候选题。

    默认使用本地确定性排序，避免每轮额外一次 LLM 调用；如需旧的 LLM
    精排，可设置 CHAT_LLM_RERANK_MODE=always 或 auto。
    """
    candidates = state.get("retrieved_questions", [])
    if not candidates:
        return {
            "retrieved_questions": [],
            "rerank_metadata": {
                "ranked_question_ids": [],
                "selected_basis_ids": [],
                "confidence": 0.0,
                "should_show_references": False,
                "filtered_reasons": ["no_candidates"],
            },
        }

    strategy = state.get("strategy", "deep_dive")
    negative_terms = state.get("search_negative_terms", [])
    search_query = state.get("search_query") or " ".join(state.get("keywords", []))
    target_topic = state.get("strategy_target_topic", search_query)
    rerank_goal = state.get("strategy_rerank_goal", "")

    deterministic = _deterministic_rerank_result(
        candidates,
        negative_terms,
        strategy,
        target_topic,
        search_query,
    )

    if strategy == "clarification":
        return {
            "retrieved_questions": [],
            "rerank_metadata": deterministic,
        }

    if not _should_use_llm_rerank(state, deterministic):
        logger.info(
            "Deterministic rerank: "
            f"strategy={strategy}, ranked={deterministic['ranked_question_ids']}, "
            f"selected={deterministic['selected_basis_ids']}, "
            f"confidence={deterministic['confidence']}, "
            f"show_refs={deterministic['should_show_references']}, "
            f"filtered={deterministic['filtered_reasons']}"
        )
        return {
            "retrieved_questions": deterministic["ranked_questions"],
            "rerank_metadata": deterministic,
        }

    recent = state.get("recent_messages", [])
    conversation_summary = "\n".join(
        f"{'面试官' if m.get('role') == 'assistant' else '候选人'}: {m.get('content', '')[:160]}"
        for m in recent[-6:]
    )
    if state.get("compressed_context"):
        conversation_summary = (
            f"{state.get('compressed_context')[:600]}\n{conversation_summary}"
        ).strip()

    prompt = LLM_RERANK_PROMPT.format(
        user_message=state.get("user_message", ""),
        conversation_summary=conversation_summary or "暂无",
        active_skills=", ".join(state.get("active_skills", [])) or "无",
        strategy=strategy,
        target_topic=target_topic,
        rerank_goal=rerank_goal,
        search_query=search_query,
        negative_terms=", ".join(negative_terms) or "无",
        question_type=state.get("strategy_preferred_question_type")
        or state.get("question_type")
        or "未指定",
        candidates=_format_rerank_candidates(candidates),
    )

    try:
        result = await _call_llm_with_retry(
            prompt,
            user_id=state.get("user_id"),
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception as e:
        logger.warning(f"LLM rerank 失败，使用 RRF 顺序降级: {e}")
        parsed = {
            "ranked_question_ids": [
                q.get("id") for q in candidates[:RERANK_RETURN_LIMIT]
            ],
            "selected_basis_ids": [candidates[0].get("id")] if candidates else [],
            "confidence": 0.45,
            "reasoning_summary": "llm_rerank_failed_fallback_to_rrf",
            "should_show_references": False,
        }

    validated = validate_rerank_result(
        parsed,
        candidates,
        negative_terms,
        strategy,
        target_topic,
        search_query,
    )
    logger.info(
        "LLM rerank: "
        f"strategy={strategy}, ranked={validated['ranked_question_ids']}, "
        f"selected={validated['selected_basis_ids']}, confidence={validated['confidence']}, "
        f"show_refs={validated['should_show_references']}, filtered={validated['filtered_reasons']}"
    )
    return {
        "retrieved_questions": validated["ranked_questions"],
        "rerank_metadata": validated,
    }



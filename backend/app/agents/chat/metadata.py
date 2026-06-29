"""Basis tracking and metadata extraction.

Split from pipeline.py — contains functions for building ReAct metadata,
inferring selected questions, and extracting company/round info.
"""

from __future__ import annotations

import json
import logging
import re

from app.agents.chat.question_plan import _normalize_question_text, _tokenize_for_overlap
from app.agents.chat.state import ChatState

logger = logging.getLogger("interview-boss")


def _extract_company(question: dict) -> str:
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

    plan = state.get("next_question_plan") or {}
    plan_metadata = state.get("question_plan_metadata") or {}
    selected_question = None
    selected_reason = ""

    if (
        plan.get("must_ask")
        and state.get("selected_question")
        and (
            plan_metadata.get("adherence", {}).get("adheres")
            or plan_metadata.get("repaired")
            or state.get("question_source_reason") in {"question_plan_bound", "question_plan_repaired", "question_plan_fallback"}
        )
    ):
        selected_question = state.get("selected_question")
        selected_reason = state.get("question_source_reason") or "question_plan_bound"
    else:
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

    if plan:
        metadata["question_plan"] = {
            "question_id": plan.get("question_id"),
            "source": plan.get("source"),
            "selection_reason": plan.get("selection_reason"),
            "adherence": plan_metadata.get("adherence"),
            "repaired": bool(plan_metadata.get("repaired", False)),
            "fallback_used": bool(plan_metadata.get("fallback_used", False)),
        }

    if state.get("resume_summary") and _response_references_resume(
        clean_response, state["resume_summary"]
    ):
        metadata["resume_ref"] = _get_resume_name(state["user_id"])

    if state.get("jd_text") and _response_references_jd(
        clean_response, state["jd_text"]
    ):
        metadata["jd_ref"] = _get_jd_title(state.get("jd_id"))

    return metadata, clean_response

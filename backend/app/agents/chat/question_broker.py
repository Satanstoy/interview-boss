"""Deterministic, model-independent question selection for Harness 2.0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_AUTHORIZED_SOURCES = {"question_bank", "private_question_bank", "conversation"}


def normalize_question_candidate(
    candidate: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """Map legacy bank-tool records into the Broker's authority contract."""
    if not isinstance(candidate, dict):
        raise ValueError("question broker candidate must be an object")
    ref = candidate.get("question_ref") or candidate.get("id")
    text = candidate.get("canonical_text") or candidate.get("question")
    normalized = {
        **candidate,
        "question_ref": str(ref or "").strip(),
        "canonical_text": str(text or "").strip(),
        # The caller derives this authority source from the server-side tool
        # identity.  Never trust a source label carried by the tool payload;
        # public bank tools use labels such as ``draw`` and ``search`` while
        # the Broker contract uses ``question_bank``.
        "source": source,
        "dimension": candidate.get("dimension") or candidate.get("cat2") or candidate.get("cat1"),
    }
    return normalized


@dataclass(frozen=True)
class QuestionCard:
    question_ref: str
    canonical_text: str
    allowed_focus: tuple[str, ...]
    forbidden_focus: tuple[str, ...]
    selection_reason: str
    source: str
    authority_check: bool

    def as_context(self) -> dict[str, Any]:
        return {
            "question_ref": self.question_ref,
            "canonical_text": self.canonical_text,
            "allowed_focus": list(self.allowed_focus),
            "forbidden_focus": list(self.forbidden_focus),
            "selection_reason": self.selection_reason,
            "source": self.source,
            "authority_check": self.authority_check,
        }


@dataclass(frozen=True)
class QuestionBrokerResult:
    question_card: QuestionCard
    candidates_considered: int
    candidate_refs: tuple[str, ...]
    constraints_hit: tuple[str, ...]


class QuestionBroker:
    """Select one authoritative question card after policy requests a card."""

    def select(
        self,
        *,
        candidates: list[dict[str, Any]],
        required_dimension: str | None = None,
        forbidden_refs: set[str] | None = None,
    ) -> QuestionBrokerResult:
        if not candidates:
            raise ValueError("question broker returned no candidates")
        forbidden = forbidden_refs or set()
        normalized: list[dict[str, Any]] = []
        for candidate in candidates:
            ref = str(candidate.get("question_ref") or "").strip()
            text = str(candidate.get("canonical_text") or "").strip()
            source = str(candidate.get("source") or "").strip()
            if not ref or not text or source not in _AUTHORIZED_SOURCES:
                raise ValueError("question broker authority check failed")
            if ref in forbidden:
                continue
            normalized.append(candidate)
        if not normalized:
            raise ValueError("question broker has no eligible authoritative candidate")

        ranked = sorted(
            normalized,
            key=lambda item: (
                0
                if required_dimension
                and item.get("dimension") == required_dimension
                else 1,
                -float(item.get("score") or 0.0),
                str(item.get("question_ref")),
            ),
        )
        selected = ranked[0]
        matched_dimension = bool(
            required_dimension and selected.get("dimension") == required_dimension
        )
        reason = (
            f"required_dimension:{required_dimension}"
            if matched_dimension
            else "highest_authority_rank"
        )
        card = QuestionCard(
            question_ref=str(selected["question_ref"]),
            canonical_text=str(selected["canonical_text"]),
            allowed_focus=tuple(str(item) for item in selected.get("allowed_focus", []) or []),
            forbidden_focus=tuple(
                str(item) for item in selected.get("forbidden_focus", []) or []
            ),
            selection_reason=reason,
            source=str(selected["source"]),
            authority_check=True,
        )
        return QuestionBrokerResult(
            question_card=card,
            candidates_considered=len(normalized),
            candidate_refs=tuple(str(item["question_ref"]) for item in ranked),
            constraints_hit=("required_dimension",) if matched_dimension else (),
        )


__all__ = [
    "QuestionBroker",
    "QuestionBrokerResult",
    "QuestionCard",
    "normalize_question_candidate",
]

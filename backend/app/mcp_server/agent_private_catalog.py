"""Private Agent interview catalog and server-side retrieval helpers.

The catalog is intentionally separate from ``question_bank``.  It is loaded
only by internal Agent interview tools and is never registered as an external
FastMCP tool or public question-bank source.
"""

from __future__ import annotations

import json
import random
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable


_CATALOG_PATH = Path(__file__).with_name("data") / "agent_interview_catalog.json"
_TOKEN_RE = re.compile(r"[\w+#./-]+|[\u4e00-\u9fff]")


@lru_cache(maxsize=1)
def load_agent_catalog() -> tuple[dict, ...]:
    """Load the generated private catalog once per worker."""

    if not _CATALOG_PATH.is_file():
        return ()
    payload = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    records = payload.get("questions", []) if isinstance(payload, dict) else []
    return tuple(item for item in records if isinstance(item, dict) and item.get("id"))


def _tokens(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        result.update(token.casefold() for token in _TOKEN_RE.findall(str(value or "")))
    return {token for token in result if token.strip()}


def _search_score(record: dict, query_tokens: set[str]) -> int:
    haystack = " ".join(
        str(record.get(key) or "")
        for key in ("question", "capability", "evaluation_focus", "source_section")
    ).casefold()
    tags = _tokens(record.get("tags") or [])
    score = sum(2 for token in query_tokens if token in haystack)
    score += sum(3 for token in query_tokens if token in tags)
    return score


def _public_private_item(record: dict, *, reason: str) -> dict:
    """Return the private tool's model-facing item without source provenance."""

    item = {
        "id": int(record["id"]),
        "question": str(record.get("question") or "").strip(),
        "cat1": "Agent 专项能力",
        "cat2": str(record.get("capability") or "通用 Agent 工程")[:120],
        "source": "agent_internal",
        "reason": reason,
        "tags": ",".join(record.get("tags") or []),
        "difficulty": str(record.get("difficulty") or "medium"),
        "format": str(record.get("format") or "concept"),
        "question_type": str(record.get("question_type") or "knowledge_probe"),
        "capability": str(record.get("capability") or ""),
        "evaluation_focus": list(record.get("evaluation_focus") or []),
        "must_have": list(record.get("must_have") or []),
        "bonus": list(record.get("bonus") or []),
        "red_flags": list(record.get("red_flags") or []),
        "followups": list(record.get("followups") or []),
        "fixture_summary": str(record.get("fixture_summary") or ""),
    }
    return item


def search_agent_questions(
    keywords: list[str],
    *,
    question_type: str | None = None,
    interview_format: str | None = None,
    capability: str | None = None,
    limit: int = 5,
    exclude_ids: set[int] | None = None,
) -> list[dict]:
    query = _tokens(keywords + [capability or "", interview_format or ""])
    excluded = exclude_ids or set()
    records = [
        record
        for record in load_agent_catalog()
        if int(record.get("id", 0)) not in excluded
        and (not question_type or record.get("question_type") == question_type)
        and (not interview_format or record.get("format") == interview_format)
    ]
    ranked = sorted(
        records,
        key=lambda record: (_search_score(record, query), -int(record["id"])),
        reverse=True,
    )
    return [_public_private_item(record, reason="private_agent_search") for record in ranked[:limit]]


def draw_agent_questions(
    *,
    count: int = 3,
    difficulty: str | None = None,
    question_type: str | None = None,
    interview_format: str | None = None,
    capability: str | None = None,
    exclude_ids: set[int] | None = None,
) -> list[dict]:
    excluded = exclude_ids or set()
    records = [
        record
        for record in load_agent_catalog()
        if int(record.get("id", 0)) not in excluded
        and (not difficulty or record.get("difficulty") == difficulty)
        and (not question_type or record.get("question_type") == question_type)
        and (not interview_format or record.get("format") == interview_format)
        and (not capability or capability.casefold() in str(record.get("capability") or "").casefold())
    ]
    if not records:
        return []
    picked = random.SystemRandom().sample(records, min(max(1, count), len(records)))
    return [_public_private_item(record, reason="private_agent_draw") for record in picked]


def get_agent_question(question_id: int) -> dict | None:
    try:
        wanted = int(question_id)
    except (TypeError, ValueError):
        return None
    for record in load_agent_catalog():
        if int(record.get("id", 0)) == wanted:
            return _public_private_item(record, reason="private_agent_selection")
    return None

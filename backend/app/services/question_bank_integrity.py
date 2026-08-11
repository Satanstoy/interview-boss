"""Atomic integrity helpers for question-bank JSON compatibility fields.

The question bank still exposes the historical JSON projections on
``question_bank`` while the source lineage is also stored in normalized
tables.  Every mutating entry point must canonicalize the JSON first and then
rebuild the normalized projection in the same transaction.
"""

from __future__ import annotations

from typing import Any

from app.services.question_variant_reconciliation import (
    claim_original_question_owner,
    normalize_original_question,
)


def canonicalize_sources(sources: Any) -> list[dict]:
    """Keep one source object per URL and preserve the best metadata."""

    result: list[dict] = []
    by_url: dict[str, dict] = {}
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        current = by_url.get(url)
        if current is None:
            current = {
                "url": url,
                "company": source.get("company", "") or "",
                "round": source.get("round", "") or "",
            }
            by_url[url] = current
            result.append(current)
            continue
        # A repeated URL is the same source; fill missing metadata instead of
        # creating a second JSON row.
        for field in ("company", "round"):
            if not current.get(field) and source.get(field):
                current[field] = source[field]
    return result


def canonicalize_original_payload(
    original_questions: Any, original_question_sources: Any
) -> tuple[list[str], list[dict]]:
    """Deduplicate original questions by the clustering normalization key.

    Different semantic questions are intentionally left as separate variants.
    Only exact normalized text variants collapse, and their source URLs are
    unioned into the surviving entry.
    """

    questions: list[str] = []
    entries: list[dict] = []
    by_normalized: dict[str, dict] = {}

    def add(question: Any, sources: Any = None) -> None:
        text = str(question or "").strip()
        normalized = normalize_original_question(text)
        if not normalized:
            return
        entry = by_normalized.get(normalized)
        if entry is None:
            entry = {"question": text, "sources": []}
            by_normalized[normalized] = entry
            questions.append(text)
            entries.append(entry)
        entry["sources"] = canonicalize_sources(
            list(entry.get("sources") or []) + list(sources or [])
        )

    for question in original_questions or []:
        add(question)
    for item in original_question_sources or []:
        if isinstance(item, dict):
            add(item.get("question"), item.get("sources"))

    return questions, entries


def canonicalize_question_bank_payload(
    sources: Any, original_questions: Any, original_question_sources: Any
) -> tuple[list[dict], list[str], list[dict]]:
    """Canonicalize both JSON projections before writing them to the row."""

    questions, entries = canonicalize_original_payload(
        original_questions, original_question_sources
    )
    return canonicalize_sources(sources), questions, entries


def sync_question_bank_projections(
    cursor,
    question_bank_id: int,
    sources: list[dict],
    original_questions: list[str],
    original_question_sources: list[dict],
) -> None:
    """Synchronize normalized lineage tables and fail closed on mismatch."""

    from app.db.question_bank_sources import sync_question_bank_sources

    sync_question_bank_sources(
        cursor,
        question_bank_id,
        sources,
        original_questions,
        original_question_sources,
    )

    # The migration is present in all supported databases.  Keep the check
    # conditional so lightweight legacy unit-test schemas can still exercise
    # the JSON-only path.
    tables = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "question_sources" not in tables:
        return

    qs_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(question_sources)")
    }
    active_qs = " AND deleted_at IS NULL" if "deleted_at" in qs_columns else ""
    actual_sources = {
        row[0]
        for row in cursor.execute(
            "SELECT url FROM question_sources WHERE question_bank_id = ?"
            + active_qs,
            (question_bank_id,),
        ).fetchall()
    }
    expected_sources = {source["url"] for source in sources if source.get("url")}
    if actual_sources != expected_sources:
        raise RuntimeError(
            f"question_sources 双写校验失败: qb={question_bank_id}, "
            f"expected={sorted(expected_sources)}, actual={sorted(actual_sources)}"
        )

    required_tables = {"question_original_items", "question_original_item_sources"}
    if not required_tables.issubset(tables):
        return

    qoi_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(question_original_items)")
    }
    qois_columns = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(question_original_item_sources)"
        )
    }
    active_qoi = " AND deleted_at IS NULL" if "deleted_at" in qoi_columns else ""
    active_qois = " AND deleted_at IS NULL" if "deleted_at" in qois_columns else ""
    rows = cursor.execute(
        "SELECT id, question_text FROM question_original_items "
        "WHERE question_bank_id = ?" + active_qoi,
        (question_bank_id,),
    ).fetchall()
    actual_questions = {row[1] for row in rows}
    if actual_questions != set(original_questions):
        raise RuntimeError(
            f"question_original_items 双写校验失败: qb={question_bank_id}, "
            f"expected={sorted(original_questions)}, actual={sorted(actual_questions)}"
        )

    expected_by_question = {
        item["question"]: {
            source["url"]
            for source in item.get("sources", [])
            if source.get("url")
        }
        for item in original_question_sources
    }
    for row in rows:
        actual_urls = {
            source_row[0]
            for source_row in cursor.execute(
                "SELECT url FROM question_original_item_sources "
                "WHERE original_item_id = ?" + active_qois,
                (row[0],),
            ).fetchall()
        }
        expected_urls = expected_by_question.get(row[1], set())
        if actual_urls != expected_urls:
            raise RuntimeError(
                f"question_original_item_sources 双写校验失败: qb={question_bank_id}, "
                f"question={row[1]!r}, expected={sorted(expected_urls)}, "
                f"actual={sorted(actual_urls)}"
            )


def claim_public_original_questions(
    conn, question_bank_id: int, owner_id: int | None, status: str, questions: list[str]
) -> None:
    """Claim every original variant when a public row becomes active."""

    if owner_id is not None or status != "approved":
        return
    for question in questions:
        claim_original_question_owner(conn, question, question_bank_id)

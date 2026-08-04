"""Shared job-position taxonomy and canonicalization for MCP question tools.

The database remains the source of truth for active positions.  The existing
interview distribution family mapping is used only to recognize the aliases
that the product already understands; it is not used for fuzzy matching.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable

from app.core.interview_distribution_config import JOB_FAMILY_BY_POSITION


_SPACE_RE = re.compile(r"\s+")
_SLASH_SPACE_RE = re.compile(r"\s*/\s*")
_AGENT_FAMILY = "agent_llm"
_CANONICAL_BY_FAMILY = {
    _AGENT_FAMILY: "Agent开发",
    "backend": "后端开发",
}
_FAMILY_DESCRIPTIONS = {
    _AGENT_FAMILY: "Agent、LLM 应用和大模型应用开发岗位",
    "backend": "后端服务、接口和系统开发岗位",
}


@dataclass(frozen=True)
class PositionResolution:
    """The result of an exact, normalized position lookup."""

    input_value: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    position_id: int | None = None
    description: str = ""
    job_family: str = ""


def normalize_job_position(value: str | None) -> str:
    """Normalize display-space and case differences without fuzzy matching."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = _SPACE_RE.sub(" ", text)
    return _SLASH_SPACE_RE.sub("/", text).casefold()


def _family_for_name(value: str | None) -> str | None:
    normalized = normalize_job_position(value)
    if not normalized:
        return None
    for configured_name, family in JOB_FAMILY_BY_POSITION.items():
        if normalize_job_position(configured_name) == normalized:
            return family
    return None


def _canonical_display_name(raw_name: str) -> tuple[str, str]:
    family = _family_for_name(raw_name)
    return _CANONICAL_BY_FAMILY.get(family, raw_name.strip()), family or f"position:{raw_name.strip()}"


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def load_active_position_rows() -> list[dict[str, Any]]:
    """Read active rows from the existing job_positions table."""

    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info('job_positions')").fetchall()
        }
        select_description = "description" if "description" in columns else "'' AS description"
        if "is_deleted" in columns:
            where = "WHERE is_deleted = 0 OR is_deleted IS NULL"
        else:
            where = ""
        rows = conn.execute(
            f"SELECT id, name, {select_description} FROM job_positions {where} ORDER BY name"
        ).fetchall()
    return [dict(row) for row in rows]


def _aliases_for_family(family: str | None) -> list[str]:
    if not family:
        return []
    aliases: list[str] = []
    for configured_name, configured_family in JOB_FAMILY_BY_POSITION.items():
        if configured_family == family and configured_name not in aliases:
            aliases.append(configured_name)
    if family == _AGENT_FAMILY and "Agent 开发" not in aliases:
        aliases.insert(0, "Agent 开发")
    return aliases


def _resolution_for_row(value: str, row: dict[str, Any]) -> PositionResolution:
    raw_name = str(row.get("name") or "").strip()
    canonical_name, family = _canonical_display_name(raw_name)
    aliases = _aliases_for_family(family)
    if raw_name and normalize_job_position(raw_name) != normalize_job_position(canonical_name):
        aliases.append(raw_name)
    # Keep aliases deterministic and never expose the canonical name twice.
    unique_aliases = tuple(
        alias
        for index, alias in enumerate(aliases)
        if alias.strip()
        and normalize_job_position(alias) != normalize_job_position(canonical_name)
        and all(normalize_job_position(alias) != normalize_job_position(other) for other in aliases[:index])
    )
    return PositionResolution(
        input_value=value,
        canonical_name=canonical_name,
        aliases=unique_aliases,
        position_id=int(row["id"]) if row.get("id") is not None else None,
        description=str(row.get("description") or "").strip()
        or _FAMILY_DESCRIPTIONS.get(family, ""),
        job_family=family,
    )


def resolve_job_position(
    value: str | None,
    *,
    position_rows: Iterable[dict[str, Any]] | None = None,
) -> PositionResolution | None:
    """Resolve a position using exact normalized aliases.

    ``None`` and whitespace-only values mean no explicit position filter.  A
    non-empty value either resolves to an active database row or returns
    ``None``; no substring or cross-family fuzzy matching is performed.
    """

    normalized_value = normalize_job_position(value)
    if not normalized_value:
        return None
    rows = list(position_rows) if position_rows is not None else load_active_position_rows()
    for row in rows:
        if not str(row.get("name") or "").strip():
            continue
        resolution = _resolution_for_row(str(value), row)
        accepted = {resolution.canonical_name, *resolution.aliases, str(row.get("name") or "")}
        if any(normalize_job_position(candidate) == normalized_value for candidate in accepted):
            return resolution
    return None


def list_job_positions() -> list[dict[str, Any]]:
    """Return active database positions with canonical names and aliases."""

    items: list[dict[str, Any]] = []
    for row in load_active_position_rows():
        resolution = _resolution_for_row(str(row.get("name") or ""), row)
        items.append(
            {
                "id": resolution.position_id,
                "name": resolution.canonical_name,
                "aliases": list(resolution.aliases),
                "description": resolution.description,
            }
        )
    return items


def position_suggestions(position_rows: Iterable[dict[str, Any]] | None = None) -> list[str]:
    """Return canonical active names for an unknown-position response."""

    rows = list(position_rows) if position_rows is not None else load_active_position_rows()
    names: list[str] = []
    for row in rows:
        resolution = _resolution_for_row(str(row.get("name") or ""), row)
        if resolution.canonical_name not in names:
            names.append(resolution.canonical_name)
    return names[:10]

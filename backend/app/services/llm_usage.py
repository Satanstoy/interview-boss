"""Provider-neutral token and prompt-cache usage normalization."""

from __future__ import annotations

from typing import Any


def normalize_cache_usage(usage: Any) -> dict[str, int | None]:
    """Normalize OpenAI-compatible and Anthropic cache usage fields."""

    def value(source: Any, key: str) -> Any:
        if source is None:
            return None
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    def integer(source: Any, *keys: str) -> int | None:
        for key in keys:
            raw = value(source, key)
            if isinstance(raw, bool):
                continue
            try:
                if raw is not None:
                    return int(raw)
            except (TypeError, ValueError):
                continue
        return None

    input_details = value(usage, "prompt_tokens_details") or value(
        usage, "input_tokens_details"
    )
    cached_from_details = integer(input_details, "cached_tokens")
    cache_read_input_tokens = integer(usage, "cache_read_input_tokens")
    cache_write_from_details = integer(input_details, "cache_write_tokens")
    return {
        "input_tokens": integer(usage, "prompt_tokens", "input_tokens"),
        "output_tokens": integer(usage, "completion_tokens", "output_tokens"),
        "total_tokens": integer(usage, "total_tokens"),
        "cached_input_tokens": cached_from_details
        if cached_from_details is not None
        else cache_read_input_tokens,
        "cache_write_input_tokens": cache_write_from_details
        if cache_write_from_details is not None
        else integer(usage, "cache_creation_input_tokens"),
        "cache_read_input_tokens": cache_read_input_tokens,
    }


def aggregate_cache_usage(
    usages: list[dict[str, int | None]],
) -> dict[str, int | None]:
    """Aggregate usage while preserving fields providers did not return."""

    totals: dict[str, int | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cached_input_tokens": None,
        "cache_write_input_tokens": None,
    }
    for usage in usages:
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] = value if totals[key] is None else totals[key] + value
        if (
            totals["cached_input_tokens"] is None
            and isinstance(usage.get("cache_read_input_tokens"), int)
            and not isinstance(usage.get("cache_read_input_tokens"), bool)
        ):
            totals["cached_input_tokens"] = usage["cache_read_input_tokens"]
    return totals

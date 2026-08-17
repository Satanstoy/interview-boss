"""Prompt-cache helpers for the ReAct request boundary.

The model provider owns the actual KV/prompt cache.  This module only creates a
stable, non-reversible fingerprint for the reusable prefix so callers can
correlate provider usage with the prompt shape without logging prompt content.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


PROMPT_CACHE_SCHEMA_VERSION = "react-prompt-v1"


def build_prompt_cache_fingerprint(
    stable_system_prompt: str,
    tools: list[dict] | None,
    model: str | None,
) -> str:
    """Return a deterministic fingerprint for a reusable prompt prefix.

    Dynamic messages are deliberately not part of the fingerprint.  Tool
    definitions are included because provider prompt caches require them to be
    identical for the prefix to be reusable.
    """

    payload: dict[str, Any] = {
        "schema": PROMPT_CACHE_SCHEMA_VERSION,
        "model": model or "",
        "stable_system_prompt": stable_system_prompt,
        "tools": tools or [],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]

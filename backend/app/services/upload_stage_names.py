"""Canonical names for durable upload stage checkpoints and call ledgers."""

from __future__ import annotations


_UPLOAD_STAGE_ALIASES = {
    "preflight": "credential_preflight",
    "complete": "extract",
    "fill": "extract",
    "tag": "classify",
    "match": "resolve",
    "cluster": "resolve",
    "save": "persist",
}

_UPLOAD_PHASE_CHECKPOINTS = {
    "extract": ("extract", "document"),
    "fill": ("extract", "document"),
    "tag": ("classify", "document"),
    "match": ("resolve", "document"),
    "save": ("persist", "document"),
    "cluster": ("resolve", "document"),
}


def canonical_upload_stage(stage: str) -> str:
    """Translate legacy graph phase names to the upload contract vocabulary."""

    value = str(stage or "")
    return _UPLOAD_STAGE_ALIASES.get(value, value)


def checkpoint_for_upload_phase(phase: str) -> tuple[str, str]:
    """Return the durable stage and unit for a legacy progress phase."""

    value = str(phase or "")
    return _UPLOAD_PHASE_CHECKPOINTS.get(
        value, (canonical_upload_stage(value), "document")
    )

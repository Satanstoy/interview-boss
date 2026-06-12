"""Compatibility exports for chat skill loading."""

from app.agents.shared.skills.loader import load_skill_from_file, _parse_skill_md

__all__ = ["load_skill_from_file", "_parse_skill_md"]

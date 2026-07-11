"""SummaryWriter — schema-valid interview feedback for close contracts."""

from __future__ import annotations

from app.agents.chat.state import ChatState
from app.agents.chat.summary import _generate_structured_summary


async def generate_structured_summary(
    state: ChatState,
    *,
    allow_fallback: bool = False,
) -> str:
    """Generate the structured summary; close contracts never permit fallback."""
    return await _generate_structured_summary(state, allow_fallback=allow_fallback)

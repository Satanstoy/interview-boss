"""Prompt context projection for Harness-aware ReAct turns."""

from __future__ import annotations

import json

from app.agents.chat.harness_contract import ContextBlock
from app.agents.chat.state import ChatState


def _render_context_blocks(blocks: tuple[ContextBlock, ...] | list[ContextBlock]) -> str:
    """Render ordered Harness blocks without changing their outer order."""
    return "\n".join(
        json.dumps(block.as_dict(), ensure_ascii=False, sort_keys=False)
        for block in blocks
    )


def _append_harness_call_suffix(state: ChatState, payload: dict) -> str:
    """Append one immutable observation and return only its prompt suffix."""
    pack = state.get("context_pack")
    if pack is None:
        return ""
    sequence = int(state.get("context_suffix_sequence") or 0) + 1
    state["context_suffix_sequence"] = sequence
    block = ContextBlock(
        block_id=f"call-observation:{state.get('turn_id') or state.get('conversation_id')}:{sequence}",
        block_type="observation",
        source="harness",
        content=payload,
        visibility="model",
        sequence=len(pack.call_suffix),
    )
    state["context_pack"] = pack.append_call_suffix(block)
    return _render_context_blocks((block,))


def _build_harness_react_messages(
    state: ChatState,
    prompt_parts: dict,
    *,
    asked_section: str,
    tool_contract: str,
    repetition_note: str,
) -> list[dict]:
    """Build the fixed three-segment prompt shape for a Harness turn."""
    pack = state.get("context_pack")
    if pack is None:
        return []
    initial_suffix = _append_harness_call_suffix(
        state,
        {
            "phase": "observe_propose",
            "asked_section": asked_section,
            "tool_contract": tool_contract,
            "repetition_note": repetition_note,
        },
    )
    return [
        {
            "role": "system",
            "content": prompt_parts["stable_system_prompt"]
            + "\n\n[Harness Stable Agent Prefix]\n"
            + _render_context_blocks(pack.stable_prefix),
        },
        {
            "role": "system",
            "content": prompt_parts["dynamic_context"]
            + "\n\n[Harness Frozen Turn Base]\n"
            + _render_context_blocks(pack.turn_base),
        },
        {"role": "user", "content": "[Harness Call Suffix]\n" + initial_suffix},
    ]

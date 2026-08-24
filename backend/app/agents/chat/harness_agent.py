"""Provider call adapter for Harness 2.0 Action/Attempt/Artifact traces."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.chat.harness_contract import CALL_MODES, ContextBlock
from app.services import chat_service


async def run_harness_agent_call(
    *,
    state: dict[str, Any],
    call_mode: str,
    action_key: str,
    request_payload: dict[str, Any],
    call: Callable[[], Awaitable[Any]],
    prompt_cache_key: str = "",
) -> Any:
    """Run one fixed-mode provider call and persist its complete trace."""
    if call_mode not in CALL_MODES:
        raise ValueError(f"unsupported call_mode: {call_mode}")
    turn_id = state.get("turn_id")
    if not turn_id:
        return await call()

    user_id = int(state["user_id"])
    conversation_id = str(state["conversation_id"])
    provider = str(state.get("provider") or "")
    model = str(state.get("model") or "")
    if not provider or not model:
        try:
            from app.services.llm import get_llm_client_for_user

            _, resolved_model, _, _, resolved_provider = get_llm_client_for_user(user_id)
            model = model or str(resolved_model or "")
            provider = provider or str(resolved_provider or "")
            state["model"] = model
            state["provider"] = provider
        except Exception:
            # Synthetic/offline callers may not have a configured provider;
            # production calls resolve these values through the same client
            # resolver above before the provider request is made.
            pass
    skill_hashes = sorted(
        str(skill.get("content_hash"))
        for skill in state.get("resolved_skills", [])
        if isinstance(skill, dict) and skill.get("content_hash")
    )
    sampling_payload = state.get("sampling_params") or {"temperature": 0.7}
    sampling_hash = hashlib.sha256(
        json.dumps(sampling_payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    # The TurnRun stores the frozen base hash, while each Attempt records the
    # complete ordered pack used by that call (including its append-only
    # suffix).  This keeps replay/cache provenance precise without mutating the
    # frozen Turn Base.
    context_pack = state.get("context_pack")
    added_context_blocks: tuple[ContextBlock, ...] = ()
    if context_pack is not None:
        existing_ids = {
            block.block_id
            for block in (
                context_pack.stable_prefix
                + context_pack.turn_base
                + context_pack.call_suffix
            )
        }
        if f"action:{action_key}" not in existing_ids:
            added_context_blocks = (
                ContextBlock(
                    f"call-mode:{action_key}",
                    "call_mode",
                    "harness",
                    {"call_mode": call_mode},
                    "model",
                    len(context_pack.call_suffix),
                ),
                ContextBlock(
                    f"action:{action_key}",
                    "action",
                    "harness",
                    {"request": request_payload},
                    "model",
                    len(context_pack.call_suffix) + 1,
                ),
            )
            context_pack = context_pack.append_call_suffix(*added_context_blocks)
            state["context_pack"] = context_pack
            state["context_pack_hash"] = context_pack.context_pack_hash
    if added_context_blocks:
        metadata = "\n".join(
            json.dumps(block.as_dict(), ensure_ascii=False, sort_keys=False)
            for block in added_context_blocks
        )
        if isinstance(request_payload.get("messages"), list):
            request_payload["messages"].append(
                {"role": "user", "content": "[Harness Call Metadata]\n" + metadata}
            )
        elif isinstance(request_payload.get("prompt"), str):
            request_payload["prompt"] += "\n\n[Harness Call Metadata]\n" + metadata
    context_pack_hash = str(
        getattr(context_pack, "context_pack_hash", None)
        or state.get("context_pack_hash")
        or ""
    )
    encoded_request = json.dumps(
        request_payload, ensure_ascii=False, sort_keys=True, default=str
    )
    request_hash = hashlib.sha256(encoded_request.encode("utf-8")).hexdigest()
    action = await _to_thread(
        chat_service.create_harness_action,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        action_key=action_key,
        action_type=call_mode,
        phase=call_mode,
        input_payload={"request_hash": request_hash},
        lease_owner=state.get("turn_lease_owner"),
    )
    recovered = await _to_thread(
        chat_service.get_completed_harness_attempt,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        action_id=action["id"],
        call_mode=call_mode,
        model=model,
        context_pack_hash=context_pack_hash,
        request_hash=request_hash,
        harness_version=str(state.get("harness_version") or "2.0"),
        prompt_schema="agent-result-v1",
        sampling_hash=sampling_hash,
    )
    if recovered is not None:
        result = recovered.get("result")
        if isinstance(result, dict):
            returned_mode = result.get("call_mode")
            if returned_mode is not None and returned_mode != call_mode:
                raise ValueError(
                    f"recovered agent returned call_mode={returned_mode!r}; expected {call_mode!r}"
                )
        return result
    attempt = await _to_thread(
        chat_service.start_harness_attempt,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        action_id=action["id"],
        call_mode=call_mode,
        provider=provider,
        model=model,
        context_pack_hash=context_pack_hash,
        prompt_cache_key=prompt_cache_key,
        request_hash=request_hash,
        harness_version=str(state.get("harness_version") or "2.0"),
        prompt_schema="agent-result-v1",
        sampling_hash=sampling_hash,
        skill_hashes=skill_hashes,
        lease_owner=state.get("turn_lease_owner"),
    )
    await _to_thread(
        chat_service.append_harness_artifact,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        action_id=action["id"],
        attempt_id=attempt["id"],
        artifact_type="provider_request",
        content=request_payload,
        visibility="model",
        lease_owner=state.get("turn_lease_owner"),
    )
    if context_pack is not None:
        await _to_thread(
            chat_service.append_harness_artifact,
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=str(turn_id),
            action_id=action["id"],
            attempt_id=attempt["id"],
            artifact_type="context_pack",
            content={
                "stable_prefix": [item.as_dict() for item in context_pack.stable_prefix],
                "turn_base": [item.as_dict() for item in context_pack.turn_base],
                "call_suffix": [item.as_dict() for item in context_pack.call_suffix],
            },
            visibility="audit",
            lease_owner=state.get("turn_lease_owner"),
        )
        await _to_thread(
            chat_service.append_harness_artifact,
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=str(turn_id),
            action_id=action["id"],
            attempt_id=attempt["id"],
            artifact_type="context_manifest",
            content={
                "harness_version": state.get("harness_version", "2.0"),
                "prompt_schema": "agent-result-v1",
                "stable_prefix_hash": context_pack.stable_prefix_hash,
                "context_pack_hash": context_pack_hash,
                "skill_hashes": sorted(
                    str(skill.get("content_hash"))
                    for skill in state.get("resolved_skills", [])
                    if isinstance(skill, dict) and skill.get("content_hash")
                ),
                "provider": provider,
                "model": model,
                "sampling_hash": sampling_hash,
                "request_hash": request_hash,
            },
            visibility="audit",
            lease_owner=state.get("turn_lease_owner"),
        )
    await _to_thread(
        chat_service.append_turn_event,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        event_id=f"evt:{turn_id}:attempt:{attempt['id']}:started",
        event_type="action.started",
        action_id=action["id"],
        phase=call_mode,
        channel="system",
        payload={
            "call_mode": call_mode,
            "attempt_no": int(attempt["attempt_no"]),
            "request_hash": request_hash,
        },
        lease_owner=state.get("turn_lease_owner"),
    )
    try:
        result = await call()
        if isinstance(result, dict):
            returned_mode = result.get("call_mode")
            if returned_mode is not None and returned_mode != call_mode:
                raise ValueError(
                    f"agent returned call_mode={returned_mode!r}; expected {call_mode!r}"
                )
    except Exception as exc:
        await _to_thread(
            chat_service.append_harness_artifact,
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=str(turn_id),
            action_id=action["id"],
            attempt_id=attempt["id"],
            artifact_type="provider_error",
            content={"error": str(exc)[:500]},
            visibility="audit",
            lease_owner=state.get("turn_lease_owner"),
        )
        await _to_thread(
            chat_service.finish_harness_attempt,
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=str(turn_id),
            attempt_id=attempt["id"],
            status="failed",
            error_code=type(exc).__name__,
            lease_owner=state.get("turn_lease_owner"),
        )
        await _to_thread(
            chat_service.append_turn_event,
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=str(turn_id),
            event_id=f"evt:{turn_id}:attempt:{attempt['id']}:failed",
            event_type="action.failed",
            action_id=action["id"],
            phase=call_mode,
            channel="system",
        payload={"call_mode": call_mode, "error_code": type(exc).__name__},
            lease_owner=state.get("turn_lease_owner"),
        )
        raise

    await _to_thread(
        chat_service.append_harness_artifact,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        action_id=action["id"],
        attempt_id=attempt["id"],
        artifact_type="provider_response",
        content=result,
        visibility="audit",
        lease_owner=state.get("turn_lease_owner"),
    )
    await _to_thread(
        chat_service.finish_harness_attempt,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        attempt_id=attempt["id"],
        status="succeeded",
        output=result if isinstance(result, dict) else {"text": str(result or "")},
        lease_owner=state.get("turn_lease_owner"),
    )
    result_hash = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    await _to_thread(
        chat_service.append_turn_event,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=str(turn_id),
        event_id=f"evt:{turn_id}:attempt:{attempt['id']}:completed",
        event_type="action.completed",
        action_id=action["id"],
        phase=call_mode,
        channel="system",
        payload={
            "call_mode": call_mode,
            "attempt_no": int(attempt["attempt_no"]),
            "result_hash": result_hash,
        },
        lease_owner=state.get("turn_lease_owner"),
    )
    return result


async def _to_thread(func: Callable[..., Any], /, **kwargs: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(func, **kwargs)


__all__ = ["run_harness_agent_call"]

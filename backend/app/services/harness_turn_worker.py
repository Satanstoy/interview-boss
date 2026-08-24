"""Harness 2.0 TurnRun worker runtime.

The HTTP layer only reserves a TurnRun and queues this function.  All model
output is converted into immutable events here; the final assistant message
and Ledger update are committed by ``finalize_chat_turn`` in one transaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

from app.db.connection import get_db_connection
from app.services import chat_service

logger = logging.getLogger("interview-boss")


def _load_turn_context(turn_id: str) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT t.id, t.conversation_id, t.user_id, t.fence, t.status, "
            "t.user_message_id, t.client_request_id, t.revision_of_turn_id, "
            "t.turn_base_snapshot_json, "
            "u.content AS user_content, u.metadata AS user_metadata, "
            "c.mode, c.jd_id, c.resume_text "
            "FROM chat_turns t "
            "JOIN chat_conversations c ON c.id = t.conversation_id "
            "JOIN chat_messages u ON u.id = t.user_message_id "
            "WHERE t.id = ?",
            (turn_id,),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["user_metadata"] = json.loads(result.get("user_metadata") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        result["user_metadata"] = {}
    try:
        base = json.loads(result.get("turn_base_snapshot_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        base = {}
    result["turn_base_snapshot"] = base if isinstance(base, dict) else {}
    if result["turn_base_snapshot"]:
        for key in ("mode", "jd_id", "resume_text"):
            if key in result["turn_base_snapshot"]:
                result[key] = result["turn_base_snapshot"][key]
    return result


def _max_event_sequence(turn_id: str) -> int:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM interview_events WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
    return int(row["sequence"] or 0)


def _has_assistant_delta(turn_id: str) -> bool:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM interview_events WHERE turn_id = ? "
            "AND event_type = 'assistant.delta' LIMIT 1",
            (turn_id,),
        ).fetchone()
    return bool(row)


def _clean_response(content: str) -> str:
    value = str(content or "")
    value = re.sub(r"\[BASIS\].*?\[/BASIS\]", "", value, flags=re.DOTALL)
    value = re.sub(r"\[BASIS\]\{[^}]*\}", "", value)
    value = re.sub(r'"?\\?\[BASIS\\?\].*?\\?\[/BASIS\\?\]"?', "", value, flags=re.DOTALL)
    return value.strip()


async def run_harness_turn(turn_id: str, *, worker_id: str | None = None) -> dict[str, Any]:
    """Execute one queued TurnRun exactly while its DB lease is held."""
    context = await asyncio.to_thread(_load_turn_context, str(turn_id))
    if not context:
        return {"status": "missing", "turn_run_id": str(turn_id)}
    if context["status"] != "running":
        return {"status": context["status"], "turn_run_id": str(turn_id)}

    owner = worker_id or f"harness-worker:{uuid.uuid4().hex}"
    claimed = await asyncio.to_thread(
        chat_service.claim_harness_turn,
        str(turn_id),
        lease_owner=owner,
        lease_seconds=120,
    )
    if not claimed:
        return {"status": "already_claimed", "turn_run_id": str(turn_id)}

    heartbeat_stop = asyncio.Event()

    async def heartbeat_loop():
        while not heartbeat_stop.is_set():
            try:
                await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
            except asyncio.TimeoutError:
                await asyncio.to_thread(
                    chat_service.heartbeat_harness_turn,
                    str(turn_id),
                    lease_owner=owner,
                    lease_seconds=120,
                )

    heartbeat_task = asyncio.create_task(heartbeat_loop())

    event_index = await asyncio.to_thread(_max_event_sequence, str(turn_id))
    replace_recovered_output = await asyncio.to_thread(_has_assistant_delta, str(turn_id))
    full_response = ""
    assistant_started = False
    pending_metadata: dict[str, Any] | None = None
    terminal_status = "failed"

    async def persist(
        event_type: str,
        *,
        channel: str = "system",
        phase: str = "observe_propose",
        payload: dict[str, Any] | None = None,
        action_id: str | None = None,
    ) -> dict[str, Any]:
        nonlocal event_index
        event_index += 1
        return await asyncio.to_thread(
            chat_service.append_turn_event,
            user_id=int(context["user_id"]),
            conversation_id=str(context["conversation_id"]),
            turn_id=str(turn_id),
            event_id=f"evt:{turn_id}:{event_index}",
            event_type=event_type,
            action_id=action_id,
            phase=phase,
            channel=channel,
            payload=payload or {},
            lease_owner=owner,
        )

    try:
        from app.agents.chat.graph import run_chat

        jd_text = None
        if context.get("jd_id"):
            from app.services import format_jd_text, load_visible_jd

            def load_jd():
                with get_db_connection() as conn:
                    return format_jd_text(
                        load_visible_jd(conn, context["jd_id"], context["user_id"])
                    )

            jd_text = await asyncio.to_thread(load_jd)

        async for event in run_chat(
            conversation_id=str(context["conversation_id"]),
            user_id=int(context["user_id"]),
            user_message=str(context["user_content"] or ""),
            mode=context.get("mode") or "free_practice",
            jd_id=context.get("jd_id"),
            resume_text=context.get("resume_text"),
            jd_text=jd_text,
            model=(context.get("user_metadata") or {}).get("model"),
            bank_mode="all",
            turn_id=str(turn_id),
            turn_fence=int(context["fence"]),
            turn_lease_owner=owner,
            turn_base_snapshot=context.get("turn_base_snapshot") or {},
        ):
            event_type = event.get("type", "chunk")
            if event_type == "step":
                payload = {
                    "type": "step",
                    "step": event.get("step", ""),
                    "message": event.get("message", ""),
                }
                for key in ("reason", "insight", "skill_name"):
                    if event.get(key):
                        payload[key] = event[key]
                await persist(
                    "action.updated",
                    phase=str(event.get("phase") or "observe_propose"),
                    payload=payload,
                    action_id=event.get("action_id")
                    or f"step:{event.get('phase') or 'observe_propose'}:{event.get('step') or 'runtime'}",
                )
            elif event_type == "tool_step":
                await persist(
                    "action.updated",
                    channel="evidence",
                    phase=str(event.get("phase") or "observe_propose"),
                    payload=event,
                    action_id=event.get("action_id") or "tool:observe_propose",
                )
            elif event_type == "chunk":
                content = str(event.get("content") or "")
                if not assistant_started:
                    await persist(
                        "assistant.started",
                        channel="assistant",
                        phase="write_response",
                        payload={"provisional": True},
                        action_id=event.get("action_id") or "action:write_response",
                    )
                    assistant_started = True
                if event.get("replace"):
                    full_response = content
                else:
                    full_response += content
                replace_chunk = bool(event.get("replace") or replace_recovered_output)
                if replace_recovered_output:
                    replace_recovered_output = False
                    full_response = content
                await persist(
                    "assistant.delta",
                    channel="assistant",
                    phase="write_response",
                    payload={
                        "type": "chunk",
                        "content": content,
                        "replace": replace_chunk,
                    },
                    action_id=event.get("action_id") or "action:write_response",
                )
            elif event_type == "thinking_start":
                await persist(
                    "reasoning.started",
                    channel="reasoning",
                    payload={"content": ""},
                    action_id="action:observe_propose",
                )
            elif event_type == "thinking":
                await persist(
                    "reasoning.delta",
                    channel="reasoning",
                    payload={"content": event.get("content", "")},
                    action_id="action:observe_propose",
                )
            elif event_type == "thinking_done":
                await persist(
                    "reasoning.completed",
                    channel="reasoning",
                    payload={
                        "duration": event.get("duration", 0),
                        "content": event.get("content", ""),
                    },
                    action_id="action:observe_propose",
                )
            elif event_type == "retrieved":
                await persist(
                    "evidence.appended",
                    channel="evidence",
                    payload={"questions": event.get("questions", [])},
                    action_id="action:observe_propose",
                )
            elif event_type == "insight":
                await persist(
                    "reasoning.insight",
                    channel="reasoning",
                    payload=event,
                    action_id="action:observe_propose",
                )
            elif event_type == "basis":
                await persist(
                    "evidence.selected",
                    channel="evidence",
                    phase="write_response",
                    payload=event,
                    action_id="action:write_response",
                )
            elif event_type == "done":
                metadata = event.get("metadata") or {}
                if not assistant_started:
                    await persist(
                        "assistant.started",
                        channel="assistant",
                        phase="write_response",
                        payload={"provisional": True},
                    )
                    assistant_started = True
                pending_metadata = metadata
                # The generator may still run durable post-processing after
                # yielding ``done``.  Finalize only after async iteration ends.
            elif event_type == "cancelled":
                await asyncio.to_thread(
                    chat_service.cancel_chat_turn,
                    str(turn_id),
                    str(context["conversation_id"]),
                    int(context["user_id"]),
                    "worker_cancelled",
                    lease_owner=owner,
                    harness_events=True,
                )
                terminal_status = "cancelled"
                return {"status": terminal_status, "turn_run_id": str(turn_id)}
            elif event_type == "error":
                code = event.get("code") or "PIPELINE_ERROR"
                await asyncio.to_thread(
                    chat_service.fail_chat_turn,
                    str(turn_id),
                    int(context["fence"]),
                    str(context["conversation_id"]),
                    int(context["user_id"]),
                    code,
                    lease_owner=owner,
                    harness_events=True,
                )
                terminal_status = "failed"
                return {"status": terminal_status, "turn_run_id": str(turn_id)}

        if pending_metadata is not None:
            await persist(
                "commit.started",
                phase="commit",
                payload={"has_response": bool(full_response)},
            )
            clean_response = _clean_response(full_response)
            await asyncio.to_thread(
                chat_service.finalize_chat_turn,
                str(turn_id),
                int(context["fence"]),
                str(context["conversation_id"]),
                int(context["user_id"]),
                clean_response or full_response,
                {
                    **pending_metadata,
                    "turn_id": str(turn_id),
                    "turn_fence": int(context["fence"]),
                },
                harness_events=True,
                lease_owner=owner,
            )
            terminal_status = "completed"
        return {"status": terminal_status, "turn_run_id": str(turn_id)}
    except chat_service.TurnCancelled:
        try:
            await asyncio.to_thread(
                chat_service.cancel_chat_turn,
                str(turn_id),
                str(context["conversation_id"]),
                int(context["user_id"]),
                "client_stop",
                lease_owner=owner,
                harness_events=True,
            )
        except chat_service.TurnEventLeaseLost:
            logger.info("Harness lease lost while cancelling turn %s", turn_id)
            return {"status": "stale", "turn_run_id": str(turn_id)}
        return {"status": "cancelled", "turn_run_id": str(turn_id)}
    except chat_service.TurnEventLeaseLost:
        logger.info("Harness lease lost; stale worker will not write turn %s", turn_id)
        return {"status": "stale", "turn_run_id": str(turn_id)}
    except Exception:
        logger.exception("Harness 2.0 TurnRun failed: %s", turn_id)
        try:
            await asyncio.to_thread(
                chat_service.fail_chat_turn,
                str(turn_id),
                int(context["fence"]),
                str(context["conversation_id"]),
                int(context["user_id"]),
                "WORKER_ERROR",
                lease_owner=owner,
                harness_events=True,
            )
        except chat_service.TurnEventLeaseLost:
            logger.info("Harness lease lost while failing turn %s", turn_id)
        except Exception:
            logger.exception("Unable to persist failed TurnRun: %s", turn_id)
        return {"status": "failed", "turn_run_id": str(turn_id)}
    finally:
        heartbeat_stop.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        await asyncio.to_thread(
            chat_service.release_harness_turn_lease,
            str(turn_id),
            lease_owner=owner,
        )


__all__ = ["run_harness_turn"]

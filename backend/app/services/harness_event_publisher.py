"""External publication of the transactional Harness event outbox."""

from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable

from app.core.cache import get_cache_client
from app.db.connection import get_db_connection
from app.services.chat_event_service import claim_turn_event_outbox, mark_turn_event_outbox_published


def _load_event(event_id: str) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT event_id, conversation_id, turn_id, sequence, event_type, action_id, "
            "phase, channel, visibility, schema_version, payload_json, created_at "
            "FROM interview_events WHERE event_id = ?",
            (str(event_id),),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        item["payload"] = {}
    item["session_id"] = item["conversation_id"]
    item["turn_run_id"] = item["turn_id"]
    item["type"] = item["event_type"]
    item["schema_version"] = f"turn-event-v{int(item.get('schema_version') or 1)}"
    item["occurred_at"] = item.pop("created_at", None)
    return item


async def publish_pending_harness_events(
    *,
    publish: Callable[[dict[str, Any]], Any] | Callable[[dict[str, Any]], Awaitable[Any]],
    limit: int = 50,
    lease_seconds: int = 30,
) -> dict[str, int]:
    """Publish claimed user projections and retry failed broker deliveries."""
    claimed = claim_turn_event_outbox(limit=limit, lease_seconds=lease_seconds)
    published = 0
    failed = 0
    for item in claimed:
        try:
            event = _load_event(item["event_id"])
            if event is None:
                raise LookupError(f"event not found: {item['event_id']}")
            # Audit/model events stay durable but never cross the user broker.
            if event.get("visibility") == "user":
                result = publish(event)
                if inspect.isawaitable(result):
                    await result
            mark_turn_event_outbox_published(item["event_id"], success=True)
            published += 1
        except Exception as exc:
            mark_turn_event_outbox_published(
                item["event_id"], success=False, error=str(exc)[:500]
            )
            failed += 1
    return {"claimed": len(claimed), "published": published, "failed": failed}


async def publish_harness_event_to_redis(event: dict[str, Any]) -> None:
    """Publish only a sanitized user event to the projection broker."""
    client = get_cache_client()
    if client is None:
        raise RuntimeError("Harness event broker is unavailable")
    channel = f"interview-boss:harness:turn:{event['turn_run_id']}"
    await client.publish(
        channel,
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


__all__ = ["publish_pending_harness_events", "publish_harness_event_to_redis"]

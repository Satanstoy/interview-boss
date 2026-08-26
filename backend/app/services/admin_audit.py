"""Small append-only audit writer for administrative destructive actions."""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import get_db_connection


def record_admin_audit(
    event_type: str,
    status: str,
    *,
    actor_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an audit event and commit it independently of business cleanup."""
    payload = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO admin_audit_log (event_type, status, actor_id, metadata) "
            "VALUES (?, ?, ?, ?)",
            (event_type, status, actor_id, payload),
        )
        conn.commit()

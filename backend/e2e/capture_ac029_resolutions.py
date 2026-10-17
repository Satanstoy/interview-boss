"""Capture successful AC-029 identities before selective recovery."""

import json
import sys
from app.db.connection import get_db_connection

with get_db_connection() as conn:
    rows = conn.execute(
        "SELECT i.id AS contribution_item_id, i.public_detail_id, "
        "r.id AS resolution_id, r.canonical_id "
        "FROM public_contribution_items i JOIN question_resolutions r ON r.detail_id=i.public_detail_id "
        "WHERE i.request_id=? AND i.status='published' AND r.invalidated_at IS NULL "
        "AND r.occurrence_scope='public' AND r.status IN ('matched','created') ORDER BY i.id",
        (int(sys.argv[1]),),
    ).fetchall()
    if len(rows) != 3:
        raise AssertionError("expected three successful public resolutions before retry")
    print(json.dumps([dict(row) for row in rows], sort_keys=True))

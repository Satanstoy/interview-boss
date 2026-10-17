"""Upload task read APIs must return the same live answer counts."""

from __future__ import annotations

import asyncio

from app.routers.upload_imports import (
    get_upload_import,
    get_upload_import_by_key,
    list_upload_imports,
)


def test_list_detail_and_idempotency_lookup_include_answer_counts(app_db_isolation):
    conn = app_db_isolation
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, status) "
        "VALUES ('imp-counts', 101, 'key-counts', 'hash-counts', 'private', "
        "'interview', 'v1', 'completed')"
    )
    conn.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
        "pipeline_version, status) VALUES ('imp-counts', 'answer', 'answer:901', 1, "
        "'v1', 'succeeded')"
    )
    conn.commit()
    conn.execute("UPDATE upload_stage_results SET result_json = ? WHERE import_id = 'imp-counts' AND stage = 'answer'", ('{"answer_review_status":"needs_review"}',))
    conn.commit()
    user = {"id": 101, "is_admin": False}

    detail = asyncio.run(get_upload_import("imp-counts", user=user))
    by_key = asyncio.run(get_upload_import_by_key("key-counts", user=user))
    listing = asyncio.run(list_upload_imports(user=user, page=1, page_size=20))

    assert detail["counts"]["answered"] == 1
    assert by_key["counts"]["answered"] == 1
    assert listing["items"][0]["counts"]["answered"] == 1
    assert detail["counts"]["answer_needs_review"] == 1
    assert by_key["counts"]["answer_needs_review"] == 1
    assert listing["items"][0]["counts"]["answer_needs_review"] == 1

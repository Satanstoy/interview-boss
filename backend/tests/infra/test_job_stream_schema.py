import json

import pytest


@pytest.mark.asyncio
async def test_job_stream_reads_last_error_after_jobs_error_column_was_removed(test_db):
    test_db.execute(
        "INSERT INTO jobs (job_type, status, progress_total, result, last_error, created_by) "
        "VALUES ('submit_import', 'completed', 1, ?, NULL, 1)",
        (json.dumps({"jd_id": 1}),),
    )
    test_db.commit()

    from app.routers.bank_build import stream_job_progress

    response = await stream_job_progress(1, {"id": 1, "is_admin": 0})
    chunks = [chunk async for chunk in response.body_iterator]
    payload = "".join(
        chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks
    )

    assert '"type": "done"' in payload
    assert "No item with that key" not in payload

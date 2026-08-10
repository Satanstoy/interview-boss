"""聚类攒批由数据库 Job + ARQ 负责调度，不依赖进程内 asyncio task。"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_cluster_window_is_persisted_and_immediately_dispatched(test_db):
    import app.services.pipeline.queue as queue

    test_db.execute("INSERT INTO interview (id, url) VALUES (1, 'internal://1')")
    test_db.execute(
        "INSERT INTO analysis_queue (interview_id, question_detail_id, status) "
        "VALUES (1, 1, 'pending')"
    )
    test_db.commit()

    @contextmanager
    def _connection():
        yield test_db

    with patch("app.db.connection.get_db_connection", _connection), \
         patch.object(queue, "CLUSTER_DELAY_SECONDS", 0), \
         patch(
             "app.worker.enqueue_cluster_batch_job",
             new=AsyncMock(return_value=MagicMock(job_id="arq-cluster-1")),
         ) as mock_enqueue:
        assert await queue._run_cluster_batch_in_background(user_id=1) is True

    mock_enqueue.assert_awaited_once()
    row = test_db.execute(
        "SELECT job_type, status, arq_job_id FROM jobs WHERE job_type = 'cluster_batch'"
    ).fetchone()
    assert (row["job_type"], row["status"], row["arq_job_id"]) == (
        "cluster_batch",
        "queued",
        "arq-cluster-1",
    )


@pytest.mark.asyncio
async def test_cluster_window_deduplicates_active_job(test_db):
    import app.services.pipeline.queue as queue

    test_db.execute(
        "INSERT INTO jobs (job_type, status, progress_total) "
        "VALUES ('cluster_batch', 'pending', 1)"
    )
    test_db.commit()

    @contextmanager
    def _connection():
        yield test_db

    with patch("app.db.connection.get_db_connection", _connection), \
         patch("app.worker.enqueue_cluster_batch_job", new=AsyncMock()) as mock_enqueue:
        assert await queue._run_cluster_batch_in_background(user_id=1) is False

    mock_enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_cluster_window_dispatch_failure_keeps_job_pending(test_db):
    import app.services.pipeline.queue as queue

    test_db.execute("INSERT INTO interview (id, url) VALUES (1, 'internal://1')")
    test_db.execute(
        "INSERT INTO analysis_queue (interview_id, question_detail_id, status) "
        "VALUES (1, 1, 'pending')"
    )
    test_db.commit()

    @contextmanager
    def _connection():
        yield test_db

    with patch("app.db.connection.get_db_connection", _connection), \
         patch.object(queue, "CLUSTER_DELAY_SECONDS", 0), \
         patch(
             "app.worker.enqueue_cluster_batch_job",
             new=AsyncMock(side_effect=RuntimeError("Redis down")),
         ):
        assert await queue._run_cluster_batch_in_background(user_id=1) is True

    row = test_db.execute(
        "SELECT status FROM jobs WHERE job_type = 'cluster_batch'"
    ).fetchone()
    assert row["status"] == "pending"

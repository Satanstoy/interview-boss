"""audit round-3 D5 回归：全量重建题库（build_master_bank_task）不得把私有/pending 面经题目公开化。

缺陷背景：_load/_enqueue_all 无 interview.owner_id/status 过滤，私有面经题目以
analysis_queue owner_id=NULL（公共桶）入队，insert_new_clusters 硬编码 owner_id=NULL，
一次管理员重建即把全部用户私有面经写进公共题库。
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

JOB_POSITION = "后端开发"


@pytest.fixture
def _seed_rebuild_data(test_db):
    """构造 1 条公共已审核面经 + 2 条私有面经（pending / approved），各带 1 道题。"""
    conn = test_db
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (2, 'alice', 'x', 0)"
    )
    conn.execute(
        "INSERT INTO jobs (id, job_type, status, created_by) VALUES (1, 'build_master_bank', 'queued', 2)"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) VALUES (1, 'http://pub', NULL, 'approved', ?)",
        (JOB_POSITION,),
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) VALUES (2, 'http://priv-pending', 2, 'pending', ?)",
        (JOB_POSITION,),
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) VALUES (3, 'http://priv-approved', 2, 'approved', ?)",
        (JOB_POSITION,),
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, cat1, cat2, tags, diff_tag, job_position) "
        "VALUES (1, 1, 'http://pub', '公共题目', 'A', 'B', '', '', ?)",
        (JOB_POSITION,),
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, cat1, cat2, tags, diff_tag, job_position) "
        "VALUES (2, 2, 'http://priv-pending', '私有待审题目', 'A', 'B', '', '', ?)",
        (JOB_POSITION,),
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, cat1, cat2, tags, diff_tag, job_position) "
        "VALUES (3, 3, 'http://priv-approved', '私有已审题目', 'A', 'B', '', '', ?)",
        (JOB_POSITION,),
    )
    conn.commit()
    return conn


@pytest.mark.asyncio
async def test_build_master_bank_rebuild_only_enqueues_public_approved(_seed_rebuild_data):
    """私有（pending/approved）面经题目不得进入重建聚类队列与公共题库。"""
    import app.worker as worker_mod
    import app.services.pipeline.queue as queue_mod
    import app.services.pipeline.batch as batch_mod

    conn = _seed_rebuild_data
    enqueued_qd_ids: list[int] = []

    async def fake_cluster_batch(batch, **kwargs):
        enqueued_qd_ids.extend(item["qd_id"] for item in batch)
        return len(batch)

    with (
        patch("app.db.connection.get_db_connection", return_value=conn),
        patch.object(queue_mod, "get_db_connection", return_value=conn),
        patch.object(batch_mod, "get_db_connection", return_value=conn),
        patch("app.services.pipeline.cluster_batch", side_effect=fake_cluster_batch),
        patch.object(worker_mod, "shutil"),
        patch("app.db.connection.get_current_job_position", return_value=JOB_POSITION),
    ):
        result = await worker_mod.build_master_bank_task({}, 1)

    assert result["status"] == "completed"
    # 只有公共 approved 面经的题目进入聚类
    assert enqueued_qd_ids == [1]
    rows = conn.execute("SELECT question_detail_id FROM analysis_queue").fetchall()
    assert [r[0] for r in rows] == [1]
    # 公共题库中不得出现任何私有题目
    qb_rows = conn.execute(
        "SELECT question FROM question_bank WHERE owner_id IS NULL"
    ).fetchall()
    assert all("私有" not in (r[0] or "") for r in qb_rows)

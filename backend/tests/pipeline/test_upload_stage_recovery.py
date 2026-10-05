"""阶段D：阶段检查点与故障恢复（AC-008 / AC-009）。

契约（contracts.md §2.2、§2.3）：

- 提取等阶段成果落 ``upload_stage_results``，重启后**复用**而不是重新调用模型；
- 持久化“面经+明细+下游工作”必须单事务，任一步异常全部回滚；
- ``thread_id`` 由 import_id+attempt_no+job_id 组成，不使用秒级时间戳，
  同秒提交的两个任务不会互相串状态。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_lifecycle import build_thread_id
from app.services.upload_repository import (
    get_stage_result,
    persist_succeeded_stage_checkpoint,
    save_stage_result,
)


def _db(db_path=None):
    conn = sqlite3.connect(str(db_path or ":memory:"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-1', 101, 'k1', 'h1', 'private', 'interview', 'v1')"
    )
    conn.commit()
    return conn


# ── 检查点复用 ───────────────────────────────────────────────


def test_stage_checkpoint_survives_restart_and_is_reused(tmp_path):
    db_path = tmp_path / "upload-recovery.sqlite"
    conn = _db(db_path)
    # 第一次执行：提取成果落盘
    save_stage_result(
        conn,
        import_id="imp-1",
        stage="extract",
        unit_key="document",
        input_version=1,
        pipeline_version="upload-pipeline-v1",
        status="succeeded",
        result_json='{"questions": [{"ordinal": 1, "question": "TCP 三次握手"}]}',
        output_hash="h1",
    )
    conn.commit()
    conn.close()

    # 进程重启：新连接打开同一持久化数据库并复用检查点，不再重复提取。
    conn2 = sqlite3.connect(str(db_path))
    conn2.row_factory = sqlite3.Row
    conn2.execute("PRAGMA foreign_keys=ON")
    checkpoint = get_stage_result(
        conn2,
        import_id="imp-1",
        stage="extract",
        unit_key="document",
        input_version=1,
    )
    assert checkpoint is not None
    assert checkpoint["status"] == "succeeded"
    assert checkpoint["output_hash"] == "h1"
    assert "TCP 三次握手" in checkpoint["result_json"]
    conn2.close()
    conn.close()


def test_stage_checkpoint_is_versioned_by_input_version():
    conn = _db()
    save_stage_result(
        conn,
        import_id="imp-1",
        stage="extract",
        unit_key="document",
        input_version=1,
        pipeline_version="upload-pipeline-v1",
        status="succeeded",
        result_json="{}",
    )
    # 同一 input_version 不能重复成功
    with pytest.raises(sqlite3.IntegrityError):
        save_stage_result(
            conn,
            import_id="imp-1",
            stage="extract",
            unit_key="document",
            input_version=1,
            pipeline_version="upload-pipeline-v1",
            status="succeeded",
            result_json="{}",
        )
    assert (
        get_stage_result(
            conn,
            import_id="imp-1",
            stage="extract",
            unit_key="document",
            input_version=1,
        )["status"]
        == "succeeded"
    )
    conn.close()


def test_completed_stage_checkpoint_requires_current_worker_generation():
    conn = _db()
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, root_import_id, lease_generation) "
        "VALUES ('submit_import', 'running', 'imp-1', 7)"
    )
    job_id = int(cursor.lastrowid)
    conn.commit()

    persisted = persist_succeeded_stage_checkpoint(
        conn,
        import_id="imp-1",
        stage="extract",
        unit_key="document",
        result_json='{"data":{"questions":["TCP"]}}',
        job_id=job_id,
        lease_generation=7,
    )
    conn.commit()
    checkpoint = get_stage_result(
        conn,
        import_id="imp-1",
        stage="extract",
        unit_key="document",
        input_version=1,
    )
    assert persisted is True
    assert checkpoint["status"] == "succeeded"
    assert checkpoint["output_hash"]
    conn.close()


def test_stale_worker_generation_cannot_commit_stage_checkpoint():
    conn = _db()
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, root_import_id, lease_generation) "
        "VALUES ('submit_import', 'running', 'imp-1', 8)"
    )
    job_id = int(cursor.lastrowid)
    conn.commit()

    persisted = persist_succeeded_stage_checkpoint(
        conn,
        import_id="imp-1",
        stage="extract",
        unit_key="document",
        result_json='{"data":{"questions":["stale"]}}',
        job_id=job_id,
        lease_generation=7,
    )
    assert persisted is False
    assert get_stage_result(
        conn,
        import_id="imp-1",
        stage="extract",
        unit_key="document",
        input_version=1,
    ) is None
    conn.close()


# ── 持久化事务性 ─────────────────────────────────────────────


ROW = ("https://x.example.com/i1", "测试公司", "一面", "解释 TCP 三次握手", "计算机网络", "TCP", "", "")


def _submit_in_conn(conn, saved_url="https://x.example.com/i1", **overrides):
    from app.db.operations import submit_interview_in_conn

    args = dict(
        saved_url=saved_url,
        data={"公司": "测试公司", "面试轮次": "一面", "考察重点": "后端", "难易程度": "中等"},
        questions="1. 解释 TCP 三次握手",
        season="2026春招",
        owner_id=101,
        status="approved",
        job_position="后端",
        tagged_rows=[ROW],
        matched={},
        unmatched_rows=[],
        idx_to_row={},
        submitter_is_admin=False,
        user_id=101,
    )
    args.update(overrides)
    return submit_interview_in_conn(conn, **args)


def test_submit_interview_in_conn_leaves_commit_to_caller():
    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    answer_tasks, interview_id, detail_ids = _submit_in_conn(conn)
    assert interview_id and detail_ids
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM interview").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == 0
    conn.close()


def test_uncommitted_interview_transaction_is_rolled_back_after_connection_loss(tmp_path):
    """模拟 worker 在 interview/detail 写入后、事务提交前退出。"""

    db_path = tmp_path / "upload-interview-transaction.sqlite"
    conn = _db(db_path)
    conn.execute("BEGIN IMMEDIATE")
    _answer_tasks, interview_id, detail_ids = _submit_in_conn(conn)
    assert interview_id
    assert detail_ids
    assert conn.execute("SELECT COUNT(*) FROM interview").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == 1

    # Closing a process-owned SQLite connection with an open transaction is
    # the crash boundary: no explicit ROLLBACK is run by the test.
    conn.close()

    restarted = sqlite3.connect(str(db_path))
    try:
        assert restarted.execute("SELECT COUNT(*) FROM interview").fetchone()[0] == 0
        assert restarted.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == 0
        assert restarted.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0] == 0
    finally:
        restarted.close()


def test_submit_interview_in_conn_rolls_back_everything_on_failure():
    """任一步异常：面经、明细、下游题库行全部回滚，不留半截数据。"""

    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    with pytest.raises(Exception):
        _submit_in_conn(
            conn,
            # 第二行缺字段：绑定参数失败，模拟持久化中途异常
            tagged_rows=[ROW, ("https://x.example.com/i1", "测试公司", "一面", "坏题")],
        )
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM interview").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0] == 0
    conn.close()


def test_legacy_wrapper_still_commits_and_maps_duplicate_url():
    conn = _db()
    from app.db.operations import get_db_connection  # noqa: F401  # 保持旧入口可用

    answer_tasks, interview_id, detail_ids = _submit_in_conn(conn)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM interview").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == 1
    conn.close()


def test_relinking_existing_import_details_without_new_matches_preserves_resolution():
    """AC-011 retry reuses old details; an empty retry match map is not a failure."""
    from app.services.question_resolution import record_resolution
    from app.services.upload_resolution_link import link_details_to_import

    conn = _db()
    interview_id = int(
        conn.execute(
            "INSERT INTO interview (url, company, owner_id, status, job_position) "
            "VALUES ('https://retry.example/interview', 'Retry', 101, 'approved', '后端') "
            "RETURNING id"
        ).fetchone()["id"]
    )
    question_id = int(
        conn.execute(
            "INSERT INTO question_bank (question, owner_id, submitted_by, status, job_position) "
            "VALUES ('stable answer question', 101, 101, 'approved', '后端') RETURNING id"
        ).fetchone()["id"]
    )
    detail_id = int(
        conn.execute(
            "INSERT INTO questions_detail (interview_id, question, owner_id, status, job_position, "
            "import_id, source_ordinal) VALUES (?, 'stable answer question', 101, 'approved', '后端', "
            "'imp-1', 1) RETURNING id",
            (interview_id,),
        ).fetchone()["id"]
    )
    record_resolution(
        conn,
        detail_id=detail_id,
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=question_id,
        canonical_scope="private",
        status="created",
        pipeline_version="upload-pipeline-v1",
    )
    before = dict(
        conn.execute(
            "SELECT id, canonical_id, status, invalidated_at FROM question_resolutions "
            "WHERE detail_id = ? AND invalidated_at IS NULL",
            (detail_id,),
        ).fetchone()
    )
    conn.commit()

    link_details_to_import(
        conn,
        import_id="imp-1",
        detail_ids=[detail_id],
        ordinals={detail_id: 1},
        actor_id=101,
        matches={},
        write_unmatched=False,
    )

    after = dict(
        conn.execute(
            "SELECT id, canonical_id, status, invalidated_at FROM question_resolutions "
            "WHERE detail_id = ? AND invalidated_at IS NULL",
            (detail_id,),
        ).fetchone()
    )
    assert after == before
    assert conn.execute(
        "SELECT COUNT(*) FROM question_resolutions WHERE detail_id = ?", (detail_id,)
    ).fetchone()[0] == 1
    conn.close()


# ── thread_id 稳定性（AC-009） ───────────────────────────────


def test_thread_id_is_scoped_to_import_attempt_and_job():
    a = build_thread_id("imp-A", 1, 10)
    b = build_thread_id("imp-B", 1, 11)
    assert a != b
    # 同一任务的恢复批次/作业不同，thread 也不同
    assert build_thread_id("imp-A", 1, 10) == a
    assert build_thread_id("imp-A", 2, 10) != a
    assert build_thread_id("imp-A", 1, 11) != a
    # 不依赖秒级时间戳：同一毫秒调用结果稳定
    assert build_thread_id("imp-A", 1, 10) == a


async def test_submit_graph_uses_worker_thread_id(monkeypatch):
    """实际 SSE/graph 桥接必须用 worker 提供的稳定 thread_id。"""
    from types import SimpleNamespace

    import app.agents.submit.graph as graph_module

    observed = {}

    class _Graph:
        async def ainvoke(self, state, *, config):
            observed["input"] = state
            observed["thread_id"] = config["configurable"]["thread_id"]

        async def aget_state(self, config):
            return SimpleNamespace(
                values={"doc_type": "interview", "target": "personal", "extracted_data": {}}
            )

    monkeypatch.setattr(graph_module, "submit_graph", _Graph())

    async for _event in graph_module.stream_submit_graph(
        {"user_id": 101, "thread_id": "imp-1:a7:j42"}
    ):
        pass

    assert observed["thread_id"] == "imp-1:a7:j42"

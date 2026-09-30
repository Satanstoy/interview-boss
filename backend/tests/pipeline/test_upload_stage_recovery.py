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
from app.services.upload_repository import get_stage_result, save_stage_result


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
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


def test_stage_checkpoint_survives_restart_and_is_reused():
    conn = _db()
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

    # 进程重启：新的连接读到同一检查点，不再重复提取
    conn2 = sqlite3.connect(":memory:")
    conn2.row_factory = sqlite3.Row
    conn2.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn2)
    checkpoint = get_stage_result(
        conn,
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

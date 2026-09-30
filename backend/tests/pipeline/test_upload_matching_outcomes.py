

# ── AC-006：match_outcomes 三态在真实节点的行为 ────────────────────

# 本文最后一条用例走真实 worker 节点 + 隔离 DB，遵循 AC-028 协议：
# 显式 UPLOAD_TEST_DB_PATH + UPLOAD_TEST_REDIS_PREFIX 才运行（默认套件跳过）。
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("UPLOAD_TEST_DB_PATH"),
    reason="set UPLOAD_TEST_DB_PATH / UPLOAD_TEST_REDIS_PREFIX to run node-level AC-006 test",
)


def test_node_match_outcomes_three_state_honors_failure_without_new_canonical():
    """AC-006：匹配模型失败（failed）→ 该题不进聚类队列、不建新 canonical、
    resolution 记 failed（可恢复），绝不因 401/超时新建规范题。"""

    import asyncio

    from unittest.mock import AsyncMock, patch

    from app.agents.submit.persist_personal import match_and_persist_personal_node

    # 构造 valid_rows（两个非空行）：一行模型失败、一行真无候选
    tagged_rows = [
        ["https://test.com/1", "字节", "一面", "TCP握手", "数据库", "Redis", "缓存", "L2-中等"],
        ["https://test.com/2", "字节", "二面", "Redis持久化", "数据库", "Redis", "持久化", "L2-中等"],
    ]
    extracted_data = {
        "公司": "字节",
        "面试轮次": "一面",
        "具体题目清单": ["TCP握手", "Redis持久化"],
    }
    # 个人匹配失败、公共匹配 no_match（无候选）→ 只对 no_match 建新题
    outcomes = {
        "results": [
            {
                "new_id": 0,
                "ordinal": 1,
                "cat2": "Redis",
                "outcome": "failed",
                "error_code": "UPSTREAM_TIMEOUT",
                "retryable": True,
            },
            {
                "new_id": 1,
                "ordinal": 2,
                "cat2": "Redis",
                "outcome": "no_match",
                "reason": "no_candidates",
            },
        ]
    }

    enqueued = []

    def _fake_enqueue(interview_id, *, owner_id=None, question_detail_ids=None, **kw):
        enqueued.extend(question_detail_ids or [])
        return 0

    from unittest.mock import MagicMock

    # 隔离数据库（沿用 AC-028 协议：UPLOAD_TEST_DB_PATH 门禁 + 全模块 sweep）
    import os
    import sqlite3
    import app.db.connection as dbm

    _path = os.environ.get("UPLOAD_TEST_DB_PATH")
    if not _path:
        raise AssertionError("本测试必须运行在 UPLOAD_TEST_DB_PATH 隔离协议下")

    test_conn = sqlite3.connect(_path, check_same_thread=False)
    test_conn.row_factory = sqlite3.Row
    test_conn.execute("PRAGMA foreign_keys=ON")
    from app.db.migrations import run_migrations
    run_migrations(test_conn)
    test_conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) VALUES (1,'u1','x',1)"
    )
    test_conn.commit()
    dbm.DB_PATH = _path
    dbm._db_conn_var.set(test_conn)

    def _test_get_db_connection():
        return test_conn

    async def _sync_run_db(func):
        return func()

    import sys as _sys
    for _mn, _md in list(_sys.modules.items()):
        if _mn.startswith("app.") and _md is not None:
            if hasattr(_md, "run_db"):
                _md.run_db = _sync_run_db
            if hasattr(_md, "get_db_connection"):
                _md.get_db_connection = _test_get_db_connection

    with (
        patch(
            "app.services.clustering.match_outcomes",
            AsyncMock(return_value=outcomes),
        ),
        patch(
            "app.db.connection.get_current_job_position", return_value="后端开发"
        ),
        patch("app.services.pipeline.enqueue_questions", side_effect=_fake_enqueue),
        patch(
            "app.services.pipeline.queue._run_cluster_batch_in_background",
            AsyncMock(return_value=False),
        ),
        patch(
            "app.db.operations.submit_interview_txn",
            return_value=([], 9101, [601, 602]),
        ),
    ):
        state = {
            "extracted_data": extracted_data,
            "tagged_rows": tagged_rows,
            "saved_url": "https://test.com/1",
            "season": "2027届",
            "user_id": 1,
            "is_admin": True,
            "job_position": "后端开发",
        }
        result = asyncio.run(match_and_persist_personal_node(state))

    # AC-006：failed 的题（new_id=0 → detail 601）不得入队列（阻断异步建新题）；
    # no_match 的真新题（new_id=1 → detail 602）正常入队聚类。
    assert 601 not in enqueued, (
        "匹配失败（模型错误）的题目绝不能进入聚类队列异步建新题，AC-006"
    )
    assert 602 in enqueued, "no_match 真新题应正常入队聚类"
    assert result["match_failed"] == 1, "节点必须暴露 failed 计数供根状态聚合"

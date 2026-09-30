"""R12：真实全栈链路（API 事务 + worker + 真实 graph 节点 + stub 模型）。

覆盖复审要求的“实际上传→提取→分类→落库→审核→公共化→失败恢复”闭环，
**不在测试里手填中间数据**：所有 entity 由被测代码产生。

与 AC-028 同隔离协议：必须显式提供 ``UPLOAD_TEST_DB_PATH`` /
``UPLOAD_TEST_REDIS_PREFIX`` 才启动，fixture 注入连接工厂与 DB_PATH，
模型调用全部本地 stub（绝不出网）。
"""

from __future__ import annotations

import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.migrations import run_migrations

REQUIRED_ENV = ("UPLOAD_TEST_DB_PATH", "UPLOAD_TEST_REDIS_PREFIX")
_missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]

pytestmark = pytest.mark.skipif(
    bool(_missing),
    reason=(
        "R12 需要隔离环境变量："
        + ", ".join(_missing or REQUIRED_ENV)
        + "（拒绝在非隔离环境启动）"
    ),
)

TAXONOMY_STUB = {
    "configured": True,
    "categories": [
        {
            "cat1": "网络",
            "children": [{"name": "TCP"}, {"name": "HTTP"}],
        },
        {
            "cat1": "数据库",
            "children": [{"name": "Redis"}, {"name": "MySQL"}],
        },
    ],
}

EXTRACT_JSON = (
    '{"type": "interview", "data": {'
    '"公司": "某公司", "面试轮次": "一面", "考察重点": "TCP/数据库", "难易程度": "中等", '
    '"具体题目清单": ['
    '{"ordinal": 1, "question": "TCP 三次握手的过程是什么？"}, '
    '{"ordinal": 2, "question": "Redis 持久化方案有哪些优缺点？"}'
    "]}}"
)

TAGGED_ROWS = [
    ["https://u.example.com/i/1", "某公司", "一面", "TCP 三次握手的过程是什么？", "网络", "TCP", "tcp", "中等"],
    ["https://u.example.com/i/1", "某公司", "一面", "Redis 持久化方案有哪些优缺点？", "数据库", "Redis", "redis", "中等"],
]


@pytest.fixture
def isolated_stack(monkeypatch, tmp_path):
    """注入临时库与本地 stub（与 AC-028 同协议）；测试结束还原。"""

    import sys

    db_path = os.environ["UPLOAD_TEST_DB_PATH"]
    if os.path.exists(db_path):
        os.remove(db_path)

    import app.db.connection as db_module

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    for uid in (101, 201):
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
            "VALUES (?, ?, 'x', ?)",
            (uid, f"u{uid}", 1 if uid == 201 else 0),
        )
    conn.commit()

    token = db_module._db_conn_var.set(conn)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    def _test_get_db_connection():
        return conn

    async def _sync_run_db(func):
        return func()

    # 与 conftest.app_db_isolation 同强度：sweep 所有 app.* 模块引用，
    # 防止运行时局部 import 漏网打生产库（防护 fixture 兜底为显式失败）。
    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith("app.") or mod is None:
            continue
        if hasattr(mod, "run_db") and mod.run_db is not _sync_run_db:
            monkeypatch.setattr(mod, "run_db", _sync_run_db)
        if hasattr(mod, "get_db_connection"):
            monkeypatch.setattr(mod, "get_db_connection", _test_get_db_connection)

    yield conn

    db_module._db_conn_var.reset(token)
    conn.close()
    if os.path.exists(db_path):
        os.remove(db_path)


def _stub_llm():
    """让真实 graph 节点的 LLM 调用全部命中桩。"""

    return [
        # extract/complete 走 _call_llm_with_retry_messages / raw_llm_call
        patch(
            "app.services.llm._call_llm_with_retry_messages",
            AsyncMock(return_value=EXTRACT_JSON),
        ),
        patch(
            "app.services.llm.get_llm_client_for_user",
            return_value=(MagicMock(), "test-model", 30, "", "openai"),
        ),
        patch(
            "app.services.llm._should_use_response_format",
            return_value=False,
        ),
        # classify → tag_questions_batch
        patch(
            "app.services.submit_service.tag_questions_batch",
            AsyncMock(return_value=TAGGED_ROWS),
        ),
        patch(
            "app.db.connection.get_taxonomy_for_position",
            return_value=TAXONOMY_STUB,
        ),
        # 聚类攒批：不真跑（persist_public 与 pipeline.queue 都在运行时
        # 从 app.services.pipeline.queue 导入该名字，patch 源模块即可）
        patch(
            "app.services.pipeline.queue._run_cluster_batch_in_background",
            AsyncMock(return_value=False),
        ),
    ]


async def test_real_upload_to_review_to_recovery_full_chain(isolated_stack):
    """R12：真实上传→提取→落库→审核→公共化→失败恢复 全链路。"""

    from app.services.upload_lifecycle import accept_upload

    conn = isolated_stack

    # 1) 真实接受
    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="full-k-1",
        target_intent="private",
        text="面经：TCP 三次握手",
        position_id=1,
        position_name="后端",
        job_position="后端",
        credential_loaders={
            "user": lambda uid: {
                "api_key": "k",
                "base_url": "https://u.example.com/v1",
                "model": "m",
            }
        },
    )
    conn.commit()
    import_id = accepted["import_id"]
    root = conn.execute("SELECT * FROM upload_imports WHERE id = ?", (import_id,)).fetchone()
    assert root["status"] == "queued"

    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()
    submit_job = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()

    # 2) 真实预检 worker（probe stub）
    from app.services.credential_preflight import run_credential_preflight

    outcome = run_credential_preflight(
        conn,
        job_id=preflight["id"],
        probe=lambda cred: {
            "status": "ok",
            "latency_ms": 1,
            "provider": cred.provider,
        },
        user_config_loader=lambda uid: {
            "api_key": "k",
            "base_url": "https://u.example.com/v1",
            "model": "m",
            "timeout": 30,
        },
    )
    conn.commit()
    assert outcome.status == "ok"

    # 3) 真实 worker 执行（stub LLM/graph 节点仍为生产代码路径）
    from app.worker import submit_import_task

    from contextlib import ExitStack

    with ExitStack() as stack:
        for patcher in _stub_llm():
            stack.enter_context(patcher)
        await submit_import_task({}, submit_job["id"])
    conn.commit()

    # 断言：面经/明细落库且带 v2 归属 + resolution
    interview = conn.execute(
        "SELECT * FROM interview WHERE owner_id = 101 AND status = 'approved'"
    ).fetchone()
    assert interview is not None, "真实 worker 必须落库面经"
    details = conn.execute(
        "SELECT * FROM questions_detail WHERE interview_id = ? ORDER BY source_ordinal",
        (interview["id"],),
    ).fetchall()
    assert len(details) == 2
    assert all(d["import_id"] == import_id for d in details), "明细必须带 import_id"
    assert [d["source_ordinal"] for d in details] == [1, 2]
    resolutions = conn.execute(
        "SELECT * FROM question_resolutions WHERE invalidated_at IS NULL"
    ).fetchall()
    assert len(resolutions) == 2, "每道保留题都有 resolution"

    # 根任务聚合推进
    root_after = conn.execute(
        "SELECT status, revision FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert int(root_after["revision"]) >= 2

    # 4) 公共化（真实）→ v2 approve（真实物化）
    from app.models.upload_contracts import build_review_projection_request
    from app.services.public_contributions import (
        approve_public_contribution_v2,
        create_public_contribution_request,
    )

    request = create_public_contribution_request(
        conn, "interview", int(interview["id"]), 101
    )
    assert request["status"] == "pending_review"
    approval = approve_public_contribution_v2(
        conn,
        request_id=request["id"],
        admin_id=201,
        review_request=build_review_projection_request(
            {
                "expected_revision": 1,
                "review_fields": {
                    "source": {
                        "company": "某公司",
                        "round": "一面",
                        "source_url": "https://u.example.com/i/1",
                    }
                },
            },
            source_type="interview",
        ),
    )
    conn.commit()
    assert approval["public_interview_id"]
    pub_details = conn.execute(
        "SELECT COUNT(*) AS c FROM questions_detail "
        "WHERE interview_id = ?",
        (approval["public_interview_id"],),
    ).fetchone()["c"]
    assert pub_details == 2, "公共面经必须包含全部保留题"
    queued = conn.execute(
        "SELECT COUNT(*) AS c FROM analysis_queue WHERE contribution_request_id = ?",
        (request["id"],),
    ).fetchone()["c"]
    assert queued == 2, "公共题进入聚类队列"

    # 5) 失败恢复（真实 restore）→ 新 attempt + 可派发 job
    from app.services.upload_lifecycle import restore_upload

    conn.execute(
        "UPDATE upload_imports SET status = 'failed', error_code = 'UPSTREAM_TIMEOUT' "
        "WHERE id = ?",
        (import_id,),
    )
    conn.execute(
        "UPDATE jobs SET status = 'failed', worker_id = NULL, locked_until = NULL "
        "WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    )
    conn.commit()
    restored = restore_upload(conn, actor_id=101, import_id=import_id)
    conn.commit()
    assert restored["created_attempt"] is True or restored["attempt_no"] >= 1
    planned = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND status = 'pending' "
        "AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert planned is not None, "恢复必须重建可执行提取 job"
    assert planned["upload_attempt_id"] is not None

async def test_restored_attempt_reuses_extract_checkpoint_without_llm(isolated_stack):
    """F08：失败恢复后的新 attempt 复用已成功 extract/classify 检查点，
    不再重跑 LLM（计数不变）；后续阶段继续执行到完成。"""

    from unittest.mock import AsyncMock, MagicMock, patch
    from contextlib import ExitStack

    from app.services.upload_lifecycle import accept_upload, restore_upload
    from app.services.job_lifecycle import default_worker_id
    from app.worker import submit_import_task

    conn = isolated_stack
    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="resume-k-1",
        target_intent="private",
        text="面经：TCP 三次握手",
        position_id=1,
        position_name="后端",
        job_position="后端",
        credential_loaders={
            "user": lambda uid: {
                "api_key": "k",
                "base_url": "https://u.example.com/v1",
                "model": "m",
                "timeout": 30,
            }
        },
    )
    conn.commit()
    import_id = accepted["import_id"]

    def _patcher_with_counter(counter):
        return [
            patch(
                "app.services.llm._call_llm_with_retry_messages",
                AsyncMock(side_effect=lambda *a, **k: counter.__setitem__("llm", counter.get("llm", 0) + 1) or EXTRACT_JSON),
            ),
            patch(
                "app.services.llm.get_llm_client_for_user",
                return_value=(MagicMock(), "test-model", 30, "", "openai"),
            ),
            patch(
                "app.services.llm._should_use_response_format",
                return_value=False,
            ),
            patch(
                "app.services.submit_service.tag_questions_batch",
                AsyncMock(side_effect=lambda **k: counter.__setitem__("tag", counter.get("tag", 0) + 1) or TAGGED_ROWS),
            ),
            patch(
                "app.db.connection.get_taxonomy_for_position",
                return_value=TAXONOMY_STUB,
            ),
            patch(
                "app.services.pipeline.queue._run_cluster_batch_in_background",
                AsyncMock(return_value=False),
            ),
        ]

    counter = {}
    # 第一次执行：LLM 各阶段调用 1 次
    with ExitStack() as stack:
        for patcher in _patcher_with_counter(counter):
            stack.enter_context(patcher)
        await submit_import_task({}, accepted["job_id"])
    conn.commit()
    assert counter.get("llm", 0) >= 1, "第一次执行必须调用提取 LLM"
    assert counter.get("tag", 0) >= 1, "第一次执行必须调用打标"
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM questions_detail WHERE import_id = ?",
        (import_id,),
    ).fetchone()["c"] == 2

    # 失败 → 恢复 → 第二次执行：提取/打标检查点命中，不重跑 LLM
    conn.execute(
        "UPDATE upload_imports SET status = 'failed', error_code = 'UPSTREAM_TIMEOUT' "
        "WHERE id = ?",
        (import_id,),
    )
    conn.execute(
        "UPDATE jobs SET status = 'failed', worker_id = NULL, locked_until = NULL "
        "WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    )
    conn.commit()
    restored = restore_upload(conn, actor_id=101, import_id=import_id)
    conn.commit()
    new_job_id = restored["planned_job_id"]

    before_llm = counter.get("llm", 0)
    before_tag = counter.get("tag", 0)
    with ExitStack() as stack:
        for patcher in _patcher_with_counter(counter):
            stack.enter_context(patcher)
        await submit_import_task({}, new_job_id)
    conn.commit()

    assert counter.get("llm", 0) == before_llm, (
        "恢复后提取阶段应复用检查点，不重跑 LLM"
    )
    assert counter.get("tag", 0) == before_tag, (
        "恢复后分类阶段应复用检查点，不重跑打标"
    )
    # 后续阶段（persist 幂等 + 聚合）继续执行：根推进 revision / 明细不重复
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM questions_detail WHERE import_id = ?",
        (import_id,),
    ).fetchone()["c"] == 2, "恢复执行不得重复落明细"
    root = conn.execute(
        "SELECT revision FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert int(root["revision"]) >= 2

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
    import threading

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
    conn.execute(
        "INSERT OR REPLACE INTO user_llm_config (user_id, api_key, base_url, model) "
        "VALUES (101, 'k', 'https://u.example.com/v1', 'm')"
    )
    conn.commit()

    token = db_module._db_conn_var.set(conn)
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    owner_thread_id = threading.get_ident()
    thread_connections = threading.local()
    all_connections = [conn]
    connections_lock = threading.Lock()

    def _test_get_db_connection():
        if threading.get_ident() == owner_thread_id:
            return conn
        current = getattr(thread_connections, "conn", None)
        if current is None:
            current = sqlite3.connect(
                db_path, check_same_thread=False, timeout=30
            )
            current.row_factory = sqlite3.Row
            current.execute("PRAGMA foreign_keys=ON")
            thread_connections.conn = current
            with connections_lock:
                all_connections.append(current)
        return current

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
    for extra_conn in all_connections[1:]:
        extra_conn.close()
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
    )
    conn.commit()
    import_id = accepted["import_id"]
    root = conn.execute("SELECT * FROM upload_imports WHERE id = ?", (import_id,)).fetchone()
    assert root["status"] == "queued"

    preflight = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()
    assert preflight is not None
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()[0] == 0, "业务 job 只能在凭据预检通过后创建"

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
    )
    conn.commit()
    assert outcome.status == "ok"
    submit_job = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert submit_job is not None

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
    restored_preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND upload_attempt_id = ? "
        "AND job_type = 'credential_preflight' AND status = 'pending'",
        (import_id, restored["attempt_id"]),
    ).fetchone()
    assert restored_preflight is not None, "新恢复批次必须重新预检"
    from app.services.credential_preflight import run_credential_preflight

    outcome = run_credential_preflight(
        conn,
        job_id=restored_preflight["id"],
        probe=lambda cred: {
            "status": "ok",
            "latency_ms": 1,
            "provider": cred.provider,
        },
    )
    conn.commit()
    assert outcome.status == "ok"
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
    )
    conn.commit()
    import_id = accepted["import_id"]
    initial_attempt = conn.execute(
        "SELECT id FROM upload_attempts WHERE import_id = ? AND status = 'active'",
        (import_id,),
    ).fetchone()
    assert initial_attempt is not None

    # The real worker now enforces the durable preflight contract before
    # claiming this task. Run the same preflight worker against the persisted
    # user config seeded by the isolated_stack fixture.
    from app.services.credential_preflight import run_credential_preflight

    preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()
    assert preflight is not None
    outcome = run_credential_preflight(
        conn,
        job_id=preflight["id"],
        probe=lambda cred: {
            "status": "ok",
            "latency_ms": 1,
            "provider": cred.provider,
        },
    )
    conn.commit()
    assert outcome.status == "ok"
    submit_job = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import' "
        "AND upload_attempt_id = ?",
        (import_id, initial_attempt["id"]),
    ).fetchone()
    assert submit_job is not None

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
        await submit_import_task({}, submit_job["id"])
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
    restored_preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND upload_attempt_id = ? "
        "AND job_type = 'credential_preflight'",
        (import_id, restored["attempt_id"]),
    ).fetchone()
    assert restored_preflight is not None
    outcome = run_credential_preflight(
        conn,
        job_id=restored_preflight["id"],
        probe=lambda cred: {
            "status": "ok",
            "latency_ms": 1,
            "provider": cred.provider,
        },
    )
    conn.commit()
    assert outcome.status == "ok"
    new_submit_job = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND upload_attempt_id = ? "
        "AND job_type = 'submit_import'",
        (import_id, restored["attempt_id"]),
    ).fetchone()
    assert new_submit_job is not None
    new_job_id = int(new_submit_job["id"])

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


async def test_extract_checkpoint_is_committed_before_classify_failure_and_reused(
    isolated_stack, caplog,
):
    """AC-008：extract 完成后、classify 失败前的检查点必须已提交并可恢复。"""

    from contextlib import ExitStack
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.credential_preflight import run_credential_preflight
    from app.services.upload_lifecycle import accept_upload, restore_upload
    from app.worker import submit_import_task

    conn = isolated_stack
    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="ac008-extract-crash-boundary",
        target_intent="private",
        text="面经：TCP 三次握手",
        position_id=1,
        position_name="后端",
        job_position="后端",
    )
    conn.commit()
    import_id = accepted["import_id"]

    def run_preflight(attempt_id=None):
        query = (
            "SELECT id FROM jobs WHERE root_import_id = ? "
            "AND job_type = 'credential_preflight'"
        )
        params = [import_id]
        if attempt_id is not None:
            query += " AND upload_attempt_id = ?"
            params.append(attempt_id)
        preflight = conn.execute(query + " ORDER BY id DESC LIMIT 1", params).fetchone()
        assert preflight is not None
        outcome = run_credential_preflight(
            conn,
            job_id=int(preflight["id"]),
            probe=lambda credential: {
                "status": "ok",
                "provider": credential.provider,
                "model": credential.model,
                "latency_ms": 1,
            },
        )
        conn.commit()
        assert outcome.status == "ok"

    run_preflight()
    first_job = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert first_job is not None

    counters = {"extract": 0, "classify": 0}

    async def extract_once(*_args, **_kwargs):
        counters["extract"] += 1
        return EXTRACT_JSON

    async def fail_classify(**_kwargs):
        counters["classify"] += 1
        raise RuntimeError("injected failure after extraction completed")

    def patches(*, classify):
        return [
            patch(
                "app.services.llm._call_llm_with_retry_messages",
                new=AsyncMock(side_effect=extract_once),
            ),
            patch(
                "app.services.llm.get_llm_client_for_user",
                return_value=(MagicMock(), "test-model", 30, "", "openai"),
            ),
            patch("app.services.llm._should_use_response_format", return_value=False),
            patch(
                "app.services.submit_service.tag_questions_batch",
                new=AsyncMock(side_effect=classify),
            ),
            patch(
                "app.db.connection.get_taxonomy_for_position",
                return_value=TAXONOMY_STUB,
            ),
            patch(
                "app.services.pipeline.queue._run_cluster_batch_in_background",
                new=AsyncMock(return_value=False),
            ),
        ]

    with ExitStack() as stack:
        for patcher in patches(classify=fail_classify):
            stack.enter_context(patcher)
        await submit_import_task({}, int(first_job["id"]))
    conn.commit()
    assert not any(
        "Task exception was never retrieved" in record.getMessage()
        for record in caplog.records
    ), "graph error handling must close its async event stream cleanly"

    extract_checkpoint = conn.execute(
        "SELECT id, status, result_json FROM upload_stage_results "
        "WHERE import_id = ? AND stage = 'extract' AND unit_key = 'document'",
        (import_id,),
    ).fetchone()
    assert extract_checkpoint is not None
    assert extract_checkpoint["status"] == "succeeded"
    assert "TCP 三次握手" in extract_checkpoint["result_json"]
    assert counters == {"extract": 1, "classify": 1}

    restarted_reader = sqlite3.connect(os.environ["UPLOAD_TEST_DB_PATH"])
    try:
        durable_checkpoint = restarted_reader.execute(
            "SELECT status, result_json FROM upload_stage_results "
            "WHERE import_id = ? AND stage = 'extract' AND unit_key = 'document'",
            (import_id,),
        ).fetchone()
        assert durable_checkpoint is not None
        assert durable_checkpoint[0] == "succeeded"
        assert "TCP 三次握手" in durable_checkpoint[1]
    finally:
        restarted_reader.close()

    # Simulate a fresh worker generation after the later-stage failure.
    conn.execute(
        "UPDATE upload_imports SET status = 'failed', error_code = 'UPSTREAM_TIMEOUT' "
        "WHERE id = ?",
        (import_id,),
    )
    conn.execute(
        "UPDATE jobs SET status = 'failed', worker_id = NULL, locked_until = NULL "
        "WHERE id = ?",
        (first_job["id"],),
    )
    conn.commit()
    restored = restore_upload(conn, actor_id=101, import_id=import_id)
    conn.commit()
    assert restored["created_attempt"] is True
    run_preflight(restored["attempt_id"])
    retry_job = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND upload_attempt_id = ? "
        "AND job_type = 'submit_import'",
        (import_id, restored["attempt_id"]),
    ).fetchone()
    assert retry_job is not None

    async def classify_success(**_kwargs):
        counters["classify"] += 1
        return TAGGED_ROWS

    with ExitStack() as stack:
        for patcher in patches(classify=classify_success):
            stack.enter_context(patcher)
        await submit_import_task({}, int(retry_job["id"]))
    conn.commit()

    assert counters["extract"] == 1, "重启后的恢复必须复用已提交的提取检查点"
    assert counters["classify"] > 1, "恢复 attempt 必须继续执行失败的分类阶段"
    assert conn.execute(
        "SELECT COUNT(*) FROM questions_detail WHERE import_id = ?", (import_id,)
    ).fetchone()[0] == 2
    resumed_checkpoint_id = conn.execute(
        "SELECT id FROM upload_stage_results WHERE import_id = ? "
        "AND stage = 'extract' AND unit_key = 'document'",
        (import_id,),
    ).fetchone()["id"]
    assert resumed_checkpoint_id == extract_checkpoint["id"]


async def test_answer_retries_after_external_result_cannot_be_saved(isolated_stack, monkeypatch):
    """AC-008：模型已返回但答案事务失败时，可重复调用且业务答案只落一次。"""

    import json

    from app.services.credential_preflight import run_credential_preflight
    from app.services.upload_lifecycle import accept_upload
    from app.services.job_lifecycle import update_upload_answer_stage
    from app.worker import generate_answer_task

    conn = isolated_stack
    accepted = accept_upload(
        conn,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="ac008-answer-save-crash-boundary",
        target_intent="private",
        text="面经：缓存一致性",
        position_id=1,
        position_name="后端",
        job_position="后端",
    )
    conn.commit()
    import_id = accepted["import_id"]
    preflight = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? "
        "AND job_type = 'credential_preflight'",
        (import_id,),
    ).fetchone()
    assert preflight is not None
    outcome = run_credential_preflight(
        conn,
        job_id=int(preflight["id"]),
        probe=lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
    )
    assert outcome.status == "ok"

    parent = conn.execute(
        "SELECT id, upload_attempt_id FROM jobs WHERE root_import_id = ? "
        "AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert parent is not None
    conn.execute(
        "UPDATE jobs SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (parent["id"],),
    )
    question = "缓存一致性如何处理？"
    q_cursor = conn.execute(
        "INSERT INTO question_bank "
        "(question, cat1, cat2, owner_id, status, job_position) "
        "VALUES (?, '系统设计', '缓存', 101, 'approved', '后端')",
        (question,),
    )
    question_id = int(q_cursor.lastrowid)
    job_cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, "
        "upload_attempt_id, work_key) "
        "VALUES ('generate_answer', 'pending', 101, ?, ?, ?)",
        (import_id, parent["upload_attempt_id"], f"answer:{question_id}:v1"),
    )
    answer_job_id = int(job_cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (
            answer_job_id,
            json.dumps(
                {
                    "question_id": question_id,
                    "question_text": question,
                    "user_id": 101,
                    "skip_search": True,
                    "llm_scope": "user",
                    "search_scope": "user",
                }
            ),
        ),
    )
    update_upload_answer_stage(conn, answer_job_id, "pending")
    conn.execute(
        "CREATE TRIGGER ac008_fail_answer_save BEFORE UPDATE OF ai_answer ON question_bank "
        "WHEN NEW.ai_answer IS NOT OLD.ai_answer "
        "BEGIN SELECT RAISE(ABORT, 'injected answer persistence failure'); END"
    )
    conn.commit()

    from unittest.mock import AsyncMock

    answer_calls = AsyncMock(return_value="一致性答案")
    monkeypatch.setattr(
        "app.services.answer_enrichment.prepare_answer_prompt",
        AsyncMock(return_value=("prompt", [])),
    )
    monkeypatch.setattr(
        "app.services.answer_enrichment.refine_answer",
        AsyncMock(side_effect=lambda _prompt, answer, *_args, **_kwargs: (answer, [])),
    )
    monkeypatch.setattr("app.services.llm._call_llm_with_retry", answer_calls)

    failed = await generate_answer_task({}, answer_job_id)
    conn.commit()
    assert failed["status"] != "completed"
    assert answer_calls.await_count == 1, "第一次已收到模型结果，只有持久化被注入失败"
    assert conn.execute(
        "SELECT ai_answer FROM question_bank WHERE id = ?", (question_id,)
    ).fetchone()["ai_answer"] is None
    assert conn.execute(
        "SELECT status FROM upload_stage_results WHERE import_id = ? "
        "AND stage = 'answer' AND unit_key = ?",
        (import_id, f"answer:{question_id}"),
    ).fetchone()["status"] != "succeeded"

    conn.execute("DROP TRIGGER ac008_fail_answer_save")
    conn.execute(
        "UPDATE jobs SET available_at = CURRENT_TIMESTAMP WHERE id = ?",
        (answer_job_id,),
    )
    conn.commit()
    recovered = await generate_answer_task({}, answer_job_id)
    conn.commit()

    assert recovered["status"] == "completed"
    assert answer_calls.await_count == 2, "响应丢失/保存失败允许额外模型调用成本"
    assert conn.execute(
        "SELECT ai_answer FROM question_bank WHERE id = ?", (question_id,)
    ).fetchone()["ai_answer"] == "一致性答案"
    answer_stage = conn.execute(
        "SELECT status FROM upload_stage_results WHERE import_id = ? "
        "AND stage = 'answer' AND unit_key = ?",
        (import_id, f"answer:{question_id}"),
    ).fetchone()
    assert answer_stage["status"] == "succeeded"

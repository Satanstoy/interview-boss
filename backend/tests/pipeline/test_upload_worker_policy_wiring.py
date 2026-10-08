"""R02/R04：worker 从 root 读 policy 并聚合根状态的回归。

用假 graph（直接 yield done 事件）驱动 ``submit_import_task``：
- input_state 携带 root policy 的 request_public_review / credential_scope；
- worker 完成后根任务从 queued 推进到 completed/waited_review 并递增 revision；
- 失败路径把执行中阶段检查点标记为 failed，根进入 failed（可重试）。
"""

from __future__ import annotations

import json

import pytest

from app.agents.shared.events import format_sse, make_done_event


@pytest.fixture(autouse=True)
def _stable_upload_preflight_config(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.services.upload_credentials.resolve_upload_credentials",
        lambda **_kwargs: SimpleNamespace(config_fingerprint="test-fingerprint"),
    )


def _seed_root(test_db, *, target_intent="private", actor_id=101, is_admin=0):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (?, ?, 'x', ?)",
        (actor_id, f"u{actor_id}", is_admin),
    )
    policy = {
        "policy_version": 1,
        "target_intent": target_intent,
        "write_scope": "public" if (is_admin and target_intent == "share") else "private",
        "credential_scope": "user",
        "request_public_review": target_intent == "share" and not is_admin,
        "source_type": "interview",
    }
    test_db.execute(
        "INSERT INTO upload_imports ("
        "  id, requester_id, idempotency_key, request_hash, target_intent, source_type, "
        "  pipeline_version, policy_json, payload_json, status, revision"
        ") VALUES ('imp-1', ?, 'k-1', 'h-1', ?, 'interview', 'upload-pipeline-v1', ?, ?, 'queued', 1)",
        (actor_id, target_intent, json.dumps(policy), "{}"),
    )
    cursor = test_db.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, "
        "root_import_id, upload_attempt_id, work_key) "
        "VALUES ('submit_import', 'pending', 6, ?, 'imp-1', NULL, 'extract:document:v1')",
        (actor_id,),
    )
    job_id = cursor.lastrowid
    test_db.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, json.dumps({"raw_text": "面经", "user_id": actor_id, "target": "private"})),
    )
    test_db.execute(
        "INSERT INTO upload_attempts (id, import_id, attempt_no, status, requested_by) "
        "VALUES (77, 'imp-1', 1, 'active', ?)",
        (actor_id,),
    )
    attempt_id = test_db.execute(
        "SELECT id FROM upload_attempts WHERE import_id = 'imp-1'"
    ).fetchone()["id"]
    test_db.execute(
        "UPDATE jobs SET upload_attempt_id = ? WHERE id = ?", (attempt_id, job_id)
    )
    preflight_job_id = test_db.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, "
        "root_import_id, upload_attempt_id, work_key) "
        "VALUES ('credential_preflight', 'completed', 1, ?, 'imp-1', ?, "
        "'preflight:credential:v1') RETURNING id",
        (actor_id, attempt_id),
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (
            preflight_job_id,
            json.dumps(
                {
                    "root_import_id": "imp-1",
                    "requester_id": actor_id,
                    "credential_scope": "user",
                    "user_id": actor_id,
                }
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
        "pipeline_version, status, result_json, job_id) "
        "VALUES ('imp-1', 'credential_preflight', 'credential:v1:scope:user:attempt:1:run:1', 1, "
        "'upload-pipeline-v1', 'succeeded', '{\"config_fingerprint\":\"test-fingerprint\",\"model\":\"test-model\"}', ?)",
        (preflight_job_id,),
    )
    test_db.commit()
    return job_id, attempt_id


class _FakeGraph:
    """假 graph：忽略 input_state，直接产出 done 事件与最终状态。"""

    def __init__(self, final_state: dict):
        self.final_state = final_state
        self.last_input = None

    async def stream(self, input_state, result_collector=None):
        self.last_input = input_state
        doc_type = self.final_state.get("doc_type", "interview")
        target = self.final_state.get("target", "personal")
        extracted = self.final_state.get("extracted_data", {})
        yield format_sse(make_done_event(doc_type, target, extracted))
        if result_collector is not None:
            result_collector["final_state"] = dict(self.final_state)
            result_collector["answer_tasks"] = self.final_state.get("answer_tasks", [])


@pytest.fixture
def _fake_graph(monkeypatch):
    fake = _FakeGraph({"doc_type": "interview", "target": "personal", "extracted_data": {}})

    async def _stream(input_state, result_collector=None):
        # 把假 graph 的事件逐个 yield（async generator, 非 coroutine）
        fake.last_input = input_state
        doc_type = input_state.get("doc_type", "interview")
        target = input_state.get("target", "personal")
        extracted = {}
        yield format_sse(make_done_event(doc_type, target, extracted))
        if result_collector is not None:
            result_collector["final_state"] = {"doc_type": "interview", "target": "personal", "extracted_data": {}}
            result_collector["answer_tasks"] = []

    # worker 在运行时局部 import stream_submit_graph；patch 其来源模块
    monkeypatch.setattr(
        "app.agents.submit.graph.stream_submit_graph", _stream
    )
    return fake


async def test_worker_passes_root_policy_share_review_and_aggregates(
    client, monkeypatch, test_db, _fake_graph
):
    """R02/R04：share 普通用户 worker 携带 request_public_review，完成后根推进。"""

    from app.worker import submit_import_task

    job_id, attempt_id = _seed_root(test_db, target_intent="share", actor_id=101)

    async def _no_dispatch(*args, **kwargs):
        return type("J", (), {"job_id": "arq-1"})()

    await submit_import_task({}, job_id)

    # R02：policy 贯穿 input_state
    assert _fake_graph.last_input is not None
    assert _fake_graph.last_input["request_public_review"] is True
    assert "import_id" in _fake_graph.last_input
    assert "credential_scope" in _fake_graph.last_input
    from app.services.upload_lifecycle import build_thread_id

    assert attempt_id != 1, "test separates the attempt row ID from attempt_no"
    assert _fake_graph.last_input["thread_id"] == build_thread_id("imp-1", 1, job_id)

    # R04：根状态推进（非完成态至少 revision 增加/不再停在 queued）
    root = test_db.execute(
        "SELECT status, revision FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert int(root["revision"]) >= 2


async def test_worker_failure_aggregates_root_to_failed(
    client, monkeypatch, test_db, _fake_graph
):
    """R04：graph 报错 → 阶段检查点 failed、根进入 failed（可重试）。"""

    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="private", actor_id=101)

    # 让 graph 抛错
    async def _broken(input_state, result_collector=None):
        from app.agents.shared.events import make_error_event

        yield format_sse(make_error_event("UPSTREAM_TIMEOUT: 大模型超时"))

    monkeypatch.setattr(
        "app.agents.submit.graph.stream_submit_graph", _broken
    )

    await submit_import_task({}, job_id)
    monkeypatch.undo()

    root = test_db.execute(
        "SELECT status, error_code, revision FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert root["status"] in ("failed", "partial_failed")
    assert root["error_code"] == "UPSTREAM_TIMEOUT"
    assert int(root["revision"]) >= 2
    failed_stages = test_db.execute(
        "SELECT COUNT(*) AS c FROM upload_stage_results "
        "WHERE import_id = 'imp-1' AND status = 'failed'"
    ).fetchone()["c"]
    assert failed_stages >= 1


async def test_worker_projects_model_auth_failure_to_needs_action(
    client, monkeypatch, test_db
):
    """AC-013: credential errors require configuration, not a generic retry."""

    from app.agents.shared.events import make_error_event
    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="private", actor_id=101)

    async def _auth_failed(input_state, result_collector=None):
        yield format_sse(
            make_error_event("模型凭据无效，请检查配置", error_code="MODEL_AUTH_INVALID")
        )

    monkeypatch.setattr("app.agents.submit.graph.stream_submit_graph", _auth_failed)
    await submit_import_task({}, job_id)

    root = test_db.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert root["status"] == "needs_action"
    assert root["error_code"] == "MODEL_AUTH_INVALID"
    stage = test_db.execute(
        "SELECT status, error_code FROM upload_stage_results "
        "WHERE import_id = 'imp-1' AND stage = 'extract'"
    ).fetchone()
    assert stage["status"] == "needs_action"
    assert stage["error_code"] == "MODEL_AUTH_INVALID"
    job = test_db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert job["status"] == "failed"

async def test_worker_share_binds_contribution_to_root(
    client, monkeypatch, test_db
):
    """F-PUBLIC：share 完成后 worker 建公共化申请并回写
    upload_imports.contribution_request_id（端到端审计/快照链路）。"""

    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="share", actor_id=101)
    # 假 graph 返回已落库 interview_id（真实节点产物）+ 一条明细
    interview_id = test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) "
        "VALUES (777, 'internal://share-e2e', 101, 'approved', '后端开发') RETURNING id"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, company, "
        "cat1, cat2, status, owner_id) VALUES "
        "(8001, ?, 'internal://share-e2e', 'TCP 三次握手', '字节', '网络', 'TCP', 'approved', 101)",
        (interview_id,),
    )
    test_db.commit()

    async def _stream(input_state, result_collector=None):
        yield format_sse(
            make_done_event("interview", "personal", {})
        )
        if result_collector is not None:
            result_collector["final_state"] = {
                "doc_type": "interview",
                "target": "personal",
                "extracted_data": {},
                "saved_interview_id": int(interview_id),
            }
            result_collector["answer_tasks"] = []

    monkeypatch.setattr("app.agents.submit.graph.stream_submit_graph", _stream)

    await submit_import_task({}, job_id)

    root = test_db.execute(
        "SELECT contribution_request_id, status, revision FROM upload_imports "
        "WHERE id = 'imp-1'"
    ).fetchone()
    assert root["contribution_request_id"] is not None, (
        "share 完成后 root 必须绑定公共化申请（此前零写入）"
    )
    request_status = test_db.execute(
        "SELECT status FROM public_contribution_requests WHERE id = ?",
        (root["contribution_request_id"],),
    ).fetchone()
    assert request_status is not None


async def test_worker_match_failed_drives_partial_failed(
    client, monkeypatch, test_db
):
    """AC-006/UR-013：匹配模型失败（match_failed>0）→ 根任务
    partial_failed（保留已成功成果）且可重试失败步骤。"""

    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="private", actor_id=101)
    # 阶段检查点：extract 成功（有保留结果），match 阶段为 failed 占位
    test_db.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
        "pipeline_version, status) VALUES "
        "('imp-1', 'extract', 'extract:document:v1', 1, 'upload-pipeline-v1', 'succeeded'), "
        "('imp-1', 'resolve', 'match:failed:v1', 1, 'upload-pipeline-v1', 'running')"
    )
    test_db.commit()

    test_db.execute("UPDATE upload_stage_results SET job_id=? WHERE import_id='imp-1' AND unit_key IN ('extract:document:v1','match:failed:v1')", (job_id,))
    test_db.commit()

    async def _stream(input_state, result_collector=None):
        yield format_sse(make_done_event("interview", "personal", {}))
        if result_collector is not None:
            result_collector["final_state"] = {
                "doc_type": "interview",
                "target": "personal",
                "extracted_data": {},
                "match_failed": 1,
            }
            result_collector["answer_tasks"] = []

    monkeypatch.setattr("app.agents.submit.graph.stream_submit_graph", _stream)

    await submit_import_task({}, job_id)

    root = test_db.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert root["status"] == "partial_failed", (
        "匹配失败必须聚合为 partial_failed（成果保留、失败可重试）"
    )
    failed_stage = test_db.execute(
        "SELECT status FROM upload_stage_results "
        "WHERE import_id = 'imp-1' AND stage = 'resolve'"
    ).fetchone()
    assert failed_stage["status"] == "failed", "match 阶段必须标记 failed"


async def test_worker_blocks_source_deleted_after_enqueue(
    client, monkeypatch, test_db, _fake_graph
):
    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="private", actor_id=101)
    test_db.execute(
        "INSERT INTO interview (id, url, company, questions_list, owner_id, status, "
        "deleted_at, job_position) VALUES "
        "(701, 'https://source.example/701', 'S', '1.题', 101, 'approved', "
        "CURRENT_TIMESTAMP, '后端')"
    )
    test_db.execute(
        "UPDATE upload_imports SET interview_id = 701 WHERE id = 'imp-1'"
    )
    test_db.commit()

    await submit_import_task({}, job_id)

    assert _fake_graph.last_input is None, "源已删除时不能启动 graph"
    root = test_db.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert (root["status"], root["error_code"]) == ("needs_action", "SOURCE_DELETED")
    blocked = test_db.execute(
        "SELECT status FROM upload_stage_results WHERE import_id = 'imp-1' "
        "AND error_code = 'SOURCE_DELETED'"
    ).fetchone()
    assert blocked and blocked["status"] == "needs_action"


async def test_worker_blocks_position_retired_after_enqueue(
    client, monkeypatch, test_db, _fake_graph
):
    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="private", actor_id=101)
    position_id = test_db.execute(
        "INSERT INTO job_positions (name, is_deleted) VALUES ('后端', 1) RETURNING id"
    ).fetchone()["id"]
    test_db.execute(
        "UPDATE upload_imports SET position_id = ?, position_name = '后端' "
        "WHERE id = 'imp-1'",
        (position_id,),
    )
    test_db.commit()

    await submit_import_task({}, job_id)

    assert _fake_graph.last_input is None, "已退休岗位不能启动 graph"
    root = test_db.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert (root["status"], root["error_code"]) == ("needs_action", "POSITION_RETIRED")


async def test_worker_blocks_unsupported_pipeline_after_enqueue(
    client, monkeypatch, test_db, _fake_graph
):
    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="private", actor_id=101)
    test_db.execute(
        "UPDATE upload_imports SET pipeline_version = 'upload-pipeline-v999' "
        "WHERE id = 'imp-1'"
    )
    test_db.commit()

    await submit_import_task({}, job_id)

    assert _fake_graph.last_input is None, "worker 不支持该流水线版本，不能启动 graph"
    root = test_db.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert (root["status"], root["error_code"]) == (
        "needs_action",
        "PIPELINE_VERSION_UNSUPPORTED",
    )


async def test_worker_blocks_taxonomy_changed_after_enqueue(
    client, monkeypatch, test_db, _fake_graph
):
    from app.services.upload_lifecycle import _system_taxonomy_fingerprint
    from app.worker import submit_import_task

    job_id, _ = _seed_root(test_db, target_intent="private", actor_id=101)
    position_id = test_db.execute(
        "INSERT INTO job_positions (name, is_deleted) VALUES ('后端', 0) RETURNING id"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO taxonomy (position_name, categories_json, tags_json, source, owner_id) "
        "VALUES ('后端', '[{\"name\":\"网络\"}]', '[\"TCP\"]', 'system', NULL)"
    )
    fingerprint = _system_taxonomy_fingerprint(test_db, "后端")
    policy = json.loads(
        test_db.execute(
            "SELECT policy_json FROM upload_imports WHERE id = 'imp-1'"
        ).fetchone()["policy_json"]
    )
    policy["taxonomy_fingerprint"] = fingerprint
    test_db.execute(
        "UPDATE upload_imports SET position_id = ?, position_name = '后端', policy_json = ? "
        "WHERE id = 'imp-1'",
        (position_id, json.dumps(policy)),
    )
    test_db.execute(
        "UPDATE taxonomy SET categories_json = '[{\"name\":\"分布式系统\"}]' "
        "WHERE position_name = '后端' AND source = 'system' AND owner_id IS NULL"
    )
    test_db.commit()

    await submit_import_task({}, job_id)

    assert _fake_graph.last_input is None, "分类体系已变化，不能复用旧分析任务"
    root = test_db.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = 'imp-1'"
    ).fetchone()
    assert (root["status"], root["error_code"]) == ("needs_action", "TAXONOMY_CHANGED")


def test_accept_upload_persists_taxonomy_fingerprint(test_db):
    from app.services.upload_lifecycle import (
        _system_taxonomy_fingerprint,
        accept_upload,
    )

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    position_id = test_db.execute(
        "INSERT INTO job_positions (name, is_deleted) VALUES ('后端', 0) RETURNING id"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO taxonomy (position_name, categories_json, tags_json, source, owner_id) "
        "VALUES ('后端', '[{\"name\":\"网络\"}]', '[\"TCP\"]', 'system', NULL)"
    )
    test_db.commit()

    accept_upload(
        test_db,
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="taxonomy-snapshot",
        target_intent="private",
        text="请解释 TCP 三次握手。",
        position_id=position_id,
        position_name="后端",
    )
    root = test_db.execute(
        "SELECT policy_json FROM upload_imports WHERE idempotency_key = 'taxonomy-snapshot'"
    ).fetchone()
    policy = json.loads(root["policy_json"])
    assert policy["taxonomy_fingerprint"] == _system_taxonomy_fingerprint(test_db, "后端")

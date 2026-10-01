"""回归覆盖上传图的检查点恢复与失败结果持久化边界。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_classification_checkpoint_can_resume_without_reloading_taxonomy():
    from app.agents.submit.classify import classify_node

    tagged = [
        ["https://example.test/i", "公司", "一面", "解释 TCP 三次握手", "网络", "TCP", "协议", "L2-中等"]
    ]
    state = {
        "extracted_data": {"具体题目清单": ["解释 TCP 三次握手"]},
        "_resume_tagged_rows": tagged,
    }

    result = asyncio.run(classify_node(state))

    assert result["tagged_rows"] == tagged
    assert result["taxonomy_config"] == {}


def test_jd_persist_reports_zero_match_failures(monkeypatch):
    import app.db.connection as db_connection
    import app.db.operations as db_operations
    from app.agents.submit.persist_personal import jd_persist_node

    monkeypatch.setattr(db_operations, "_insert_jd", lambda *args, **kwargs: 73)

    async def run_db(func):
        return func()

    monkeypatch.setattr(db_connection, "run_db", run_db)
    state = {
        "user_id": 101,
        "target": "personal",
        "saved_url": "https://example.test/jd",
        "extracted_data": {"核心技术要求": ["Python"]},
    }

    result = asyncio.run(jd_persist_node(state))

    assert result["public_contribution_request_id"] is None
    assert result["match_failed"] == 0


def test_langgraph_preserves_match_failure_count_in_submit_state():
    from langgraph.graph import END, START, StateGraph

    from app.agents.shared.state import SubmitState

    def report_failure(state):
        return {"match_failed": 2}

    graph = StateGraph(SubmitState)
    graph.add_node("report_failure", report_failure)
    graph.add_edge(START, "report_failure")
    graph.add_edge("report_failure", END)

    result = asyncio.run(graph.compile().ainvoke({"user_id": 101}))

    assert result["match_failed"] == 2


def test_match_outcome_is_adapted_to_database_writer_contract(monkeypatch):
    import app.db.connection as db_connection
    import app.db.operations as db_operations
    from app.agents.submit.persist_personal import match_and_persist_personal_node

    submitted = {}

    class EmptyResult:
        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return EmptyResult()

    monkeypatch.setattr(db_connection, "get_db_connection", FakeConnection)

    async def run_db(func):
        return func()

    monkeypatch.setattr(db_connection, "run_db", run_db)

    def submit_interview(*args, **_kwargs):
        submitted["matched"] = args[8]
        return [], 73, [901]

    monkeypatch.setattr(db_operations, "submit_interview_txn", submit_interview)
    monkeypatch.setattr(
        "app.services.clustering.match_outcomes",
        AsyncMock(
            return_value={
                "results": [
                    {
                        "new_id": 0,
                        "outcome": "matched",
                        "canonical_id": 88,
                        "canonical_scope": "private",
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.pipeline.enqueue_questions", lambda *_args, **_kwargs: 0
    )

    state = {
        "extracted_data": {
            "公司": "公司",
            "面试轮次": "一面",
            "具体题目清单": ["解释 TCP 三次握手"],
        },
        "tagged_rows": [
            ["https://example.test/i", "公司", "一面", "解释 TCP 三次握手", "网络", "TCP", "协议", "L2-中等"]
        ],
        "saved_url": "https://example.test/i",
        "user_id": 101,
        "job_position": "后端",
    }

    asyncio.run(match_and_persist_personal_node(state))

    assert submitted["matched"][0]["question_bank_id"] == 88


def test_default_preflight_probes_the_selected_chat_model(monkeypatch):
    import app.services.credential_preflight as credential_preflight

    observed = {}

    async def create(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=1)
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.llm.build_bare_client", lambda **_kwargs: client
    )
    credential = SimpleNamespace(
        api_key="secret",
        base_url="https://model.example/v1",
        timeout=15,
        provider="openai",
        api_format="chat",
        model="configured-model",
        config_fingerprint="fingerprint",
    )

    result = credential_preflight._default_probe(credential)

    assert observed["model"] == "configured-model"
    assert observed["max_tokens"] == 1
    assert observed["messages"] == [{"role": "user", "content": "ping"}]
    assert result["input_tokens"] == 4
    assert result["output_tokens"] == 1
    assert result["model"] == "configured-model"
    client.close.assert_awaited_once()


def test_extract_uses_model_name_from_the_credential_scope(monkeypatch):
    from app.agents.submit.extract import extract_node
    import app.services.llm as llm

    selected = {}
    request = {}

    def get_client(user_id, llm_scope="user"):
        selected["scope"] = llm_scope
        return None, f"{llm_scope}-model", 30, "https://model.example/v1", "openai"

    async def call(_messages, *, user_id=None, **kwargs):
        request.update(kwargs)
        return "{}"

    monkeypatch.setattr(llm, "get_llm_client_for_user", get_client)
    monkeypatch.setattr(llm, "_call_llm_with_retry_messages", call)
    monkeypatch.setattr(llm, "_extract_json", lambda _text: {
        "type": "interview",
        "data": {
            "公司": "公司",
            "面试轮次": "一面",
            "难易程度": "中等",
            "具体题目清单": ["解释 TCP 三次握手"],
        },
    })
    monkeypatch.setattr(llm, "_should_use_response_format", lambda _url: False)

    asyncio.run(
        extract_node(
            {
                "user_id": 101,
                "credential_scope": "global",
                "content_type_hint": "interview",
                "raw_text": "解释 TCP 三次握手",
            }
        )
    )

    assert selected["scope"] == "global"
    assert request["model"] == "global-model"
    assert request["llm_scope"] == "global"


def test_completion_uses_model_name_from_the_credential_scope(monkeypatch):
    from app.agents.submit.classify import complete_node
    import app.services.llm as llm

    selected = {}
    request = {}

    def get_client(user_id, llm_scope="user"):
        selected["scope"] = llm_scope
        return None, f"{llm_scope}-model", 30, "https://model.example/v1", "openai"

    async def raw_call(user_id, **kwargs):
        request.update(kwargs)
        return "{}"

    monkeypatch.setattr(llm, "get_llm_client_for_user", get_client)
    monkeypatch.setattr(llm, "raw_llm_call", raw_call)
    monkeypatch.setattr(llm, "_extract_json", lambda _text: {})
    monkeypatch.setattr(llm, "_should_use_response_format", lambda _url: False)

    asyncio.run(
        complete_node(
            {
                "user_id": 101,
                "credential_scope": "global",
                "extracted_data": {
                    "公司": "未提供",
                    "面试轮次": "未提供",
                    "难易程度": "中等",
                    "具体题目清单": ["解释 TCP 三次握手"],
                },
            }
        )
    )

    assert selected["scope"] == "global"
    assert request["model"] == "global-model"
    assert request["llm_scope"] == "global"


def test_match_outcomes_accepts_and_uses_explicit_llm_scope(monkeypatch):
    from app.services.clustering import matcher

    observed = {}

    async def call(prompt, **kwargs):
        observed.update(kwargs)
        return '{"matches": [], "unmatched": [1]}'

    monkeypatch.setattr(matcher, "_call_llm_with_retry", call)
    rows = [{"id": 1, "question": "解释 TCP 三次握手", "cat2": "TCP"}]
    candidates = {"TCP": [{"id": 88, "question": "解释 TCP 握手"}]}

    result = asyncio.run(
        matcher.match_outcomes(
            rows, candidates, user_id=101, llm_scope="global", strict=True
        )
    )

    assert result["results"][0]["outcome"] == "no_match"
    assert observed["llm_scope"] == "global"


def test_root_submit_dispatch_waits_for_latest_same_attempt_preflight():
    import json
    import sqlite3

    from app.db.migrations import run_migrations
    from app.services.job_lifecycle import claim_dispatch_batch

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (101, 'preflight-user', 'x', 0)"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES ('preflight-root', 101, 'k', 'h', 'private', 'interview', 'v1', '{}', '{}', 'queued')"
    )
    attempt_id = conn.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES ('preflight-root', 1, 'active', 101)"
    ).lastrowid
    submit_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id) "
        "VALUES ('submit_import', 'pending', 101, 'preflight-root', ?) RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    first_preflight_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id) "
        "VALUES ('credential_preflight', 'completed', 101, 'preflight-root', ?) RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (
            first_preflight_id,
            json.dumps({"root_import_id": "preflight-root", "credential_scope": "user", "user_id": 101}),
        ),
    )

    assert claim_dispatch_batch(conn, job_type="submit_import") == []

    conn.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
        "pipeline_version, status, result_json, job_id) "
        "VALUES ('preflight-root', 'credential_preflight', 'credential:v1:attempt:1:run:1', 1, 'v1', "
        "'succeeded', ?, ?)",
        (json.dumps({"model": "model-a"}), first_preflight_id),
    )
    assert [row["id"] for row in claim_dispatch_batch(conn, job_type="submit_import")] == [
        submit_id
    ]
    conn.execute("UPDATE jobs SET status = 'pending' WHERE id = ?", (submit_id,))

    # A newer retry invalidates the old checkpoint until that exact retry passes.
    newer_preflight_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id) "
        "VALUES ('credential_preflight', 'pending', 101, 'preflight-root', ?) RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (
            newer_preflight_id,
            json.dumps({"root_import_id": "preflight-root", "credential_scope": "user", "user_id": 101}),
        ),
    )
    assert claim_dispatch_batch(conn, job_type="submit_import") == []
    conn.close()


def test_public_cluster_dispatch_requires_global_preflight_for_share():
    import json
    import sqlite3

    from app.db.migrations import run_migrations
    from app.services.job_lifecycle import claim_dispatch_batch

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'share-owner', 'x')"
    )
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (201, 'share-admin', 'x', 1)"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES ('share-cluster-root', 101, 'k', 'h', 'share', 'interview', 'v1', ?, '{}', 'queued')",
        (json.dumps({"credential_scope": "user", "post_approval_credential_scope": "global"}),),
    )
    attempt_id = conn.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES ('share-cluster-root', 1, 'completed', 101)"
    ).lastrowid
    cluster_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id, work_key) "
        "VALUES ('cluster_batch', 'pending', 201, 'share-cluster-root', ?, 'cluster:root:public:v1') "
        "RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (cluster_id, json.dumps({"root_import_id": "share-cluster-root", "credential_scope": "global", "owner_id": None})),
    )
    user_preflight_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id) "
        "VALUES ('credential_preflight', 'completed', 101, 'share-cluster-root', ?) RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (user_preflight_id, json.dumps({"root_import_id": "share-cluster-root", "credential_scope": "user", "user_id": 101})),
    )
    conn.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, pipeline_version, status, job_id) "
        "VALUES ('share-cluster-root', 'credential_preflight', 'user-check', 'v1', 'succeeded', ?)",
        (user_preflight_id,),
    )
    conn.commit()

    assert claim_dispatch_batch(conn, job_type="cluster_batch") == []

    global_preflight_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id) "
        "VALUES ('credential_preflight', 'completed', 201, 'share-cluster-root', ?) RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (global_preflight_id, json.dumps({"root_import_id": "share-cluster-root", "credential_scope": "global", "user_id": None})),
    )
    conn.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, pipeline_version, status, job_id) "
        "VALUES ('share-cluster-root', 'credential_preflight', 'global-check', 'v1', 'succeeded', ?)",
        (global_preflight_id,),
    )
    assert [row["id"] for row in claim_dispatch_batch(conn, job_type="cluster_batch")] == [
        cluster_id
    ]
    conn.close()


def test_direct_cluster_delivery_is_deferred_until_scope_probe(monkeypatch):
    import json
    import sqlite3

    from app.db.migrations import run_migrations
    import app.db.connection as db_connection
    from app.worker_cluster_tasks import _cluster_preflight_ready

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'share-owner', 'x')"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES ('direct-cluster-root', 101, 'k', 'h', 'share', 'interview', 'v1', ?, '{}', 'queued')",
        (json.dumps({"credential_scope": "user", "post_approval_credential_scope": "global"}),),
    )
    attempt_id = conn.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES ('direct-cluster-root', 1, 'completed', 101)"
    ).lastrowid
    cluster_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id, work_key) "
        "VALUES ('cluster_batch', 'queued', 101, 'direct-cluster-root', ?, 'cluster:root:public:v1') RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (cluster_id, json.dumps({"root_import_id": "direct-cluster-root", "credential_scope": "global", "owner_id": None})),
    )
    conn.commit()
    monkeypatch.setattr(db_connection, "get_db_connection", lambda: conn)

    assert asyncio.run(_cluster_preflight_ready(cluster_id)) is False
    cluster = conn.execute(
        "SELECT status, attempts FROM jobs WHERE id = ?", (cluster_id,)
    ).fetchone()
    preflight = conn.execute(
        "SELECT j.status, p.payload FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = 'direct-cluster-root' AND j.job_type = 'credential_preflight'"
    ).fetchone()
    assert tuple(cluster) == ("pending", 0)
    assert preflight["status"] == "pending"
    assert json.loads(preflight["payload"])["credential_scope"] == "global"
    conn.close()


def test_direct_worker_delivery_is_deferred_without_preflight(monkeypatch):
    import json
    import sqlite3

    from app.db.migrations import run_migrations
    import app.db.connection as db_connection
    from app.worker import submit_import_task

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (101, 'direct-worker-user', 'x', 0)"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES ('direct-root', 101, 'k', 'h', 'private', 'interview', 'v1', '{}', '{}', 'queued')"
    )
    attempt_id = conn.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES ('direct-root', 1, 'active', 101)"
    ).lastrowid
    submit_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id) "
        "VALUES ('submit_import', 'queued', 101, 'direct-root', ?) RETURNING id",
        (attempt_id,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (submit_id, json.dumps({"user_id": 101, "raw_text": "面经"})),
    )
    conn.commit()
    monkeypatch.setattr(db_connection, "get_db_connection", lambda: conn)

    result = asyncio.run(submit_import_task({}, submit_id))

    job = conn.execute(
        "SELECT status, attempts, last_error FROM jobs WHERE id = ?", (submit_id,)
    ).fetchone()
    assert result["status"] == "waiting_preflight"
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert "preflight" in job["last_error"]
    conn.close()


def test_public_cluster_results_create_one_resolution_per_source_detail():
    import sqlite3

    from app.db.migrations import run_migrations
    from app.services.pipeline.batch import _record_queue_resolutions

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'resolution-owner', 'x')"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json) "
        "VALUES ('root-a', 7, 'key-a', 'hash-a', 'share', 'interview', 'v1', '{}', '{}')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status) "
        "VALUES (91, 'https://public.example/91', NULL, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question) VALUES "
        "(901, 91, '已存在题'), (902, 91, '新题'), (903, 91, '缺失映射题')"
    )
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status, frequency) "
        "VALUES (801, '规范题', '网络', 'TCP', NULL, 'approved', 1), "
        "(802, '新规范题', '网络', 'TCP', NULL, 'approved', 1)"
    )

    rows = _record_queue_resolutions(
        conn,
        [
            {"qd_id": 901, "owner_id": None, "root_import_id": "root-a"},
            {"qd_id": 902, "owner_id": None, "contribution_request_id": 7},
            {"qd_id": 903, "owner_id": None, "root_import_id": "root-a"},
        ],
        matched_rows=[{"qd_id": 901, "cluster_id": "801"}],
        new_cluster_rows=[{"ids": ["902"]}],
        new_qb_ids=[802],
    )

    assert rows == [
        {"detail_id": 901, "canonical_id": 801, "status": "matched"},
        {"detail_id": 902, "canonical_id": 802, "status": "created"},
        {"detail_id": 903, "canonical_id": None, "status": "failed"},
    ]
    resolutions = conn.execute(
        "SELECT detail_id, canonical_id, status, occurrence_scope "
        "FROM question_resolutions ORDER BY detail_id"
    ).fetchall()
    assert [tuple(row) for row in resolutions] == [
        (901, 801, "matched", "public"),
        (902, 802, "created", "public"),
        (903, None, "failed", "public"),
    ]
    checkpoint = conn.execute(
        "SELECT status, result_json FROM upload_stage_results "
        "WHERE import_id = 'root-a' AND stage = 'resolve' AND unit_key = 'detail:901'"
    ).fetchone()
    assert checkpoint["status"] == "succeeded"
    assert '"canonical_id": 801' in checkpoint["result_json"]
    failed_checkpoint = conn.execute(
        "SELECT status, error_code FROM upload_stage_results "
        "WHERE import_id = 'root-a' AND stage = 'resolve' AND unit_key = 'detail:903'"
    ).fetchone()
    assert tuple(failed_checkpoint) == ("failed", "CLUSTER_RESOLUTION_MISSING")
    conn.close()


def test_root_stays_queued_until_async_cluster_checkpoint_finishes():
    import sqlite3

    from app.db.migrations import run_migrations
    from app.services.upload_lifecycle import finalize_attempt_and_aggregate_root

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'root-owner', 'x')"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES ('root-cluster', 101, 'key', 'hash', 'private', 'interview', 'v1', '{}', '{}', 'queued')"
    )
    conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id) "
        "VALUES ('submit_import', 'completed', 101, 'root-cluster')"
    )
    conn.execute(
        "INSERT INTO upload_stage_results "
        "(import_id, stage, unit_key, pipeline_version, status) "
        "VALUES ('root-cluster', 'persist', 'document', 'v1', 'succeeded'), "
        "('root-cluster', 'resolve', 'detail:1', 'v1', 'pending')"
    )
    conn.commit()

    pending = finalize_attempt_and_aggregate_root(
        conn, import_id="root-cluster", actor_id=101, lease_generation=0
    )
    assert pending["status"] == "queued"
    assert pending["stage"] == "resolve"

    conn.execute(
        "UPDATE upload_stage_results SET status = 'succeeded' "
        "WHERE import_id = 'root-cluster' AND stage = 'resolve'"
    )
    completed = finalize_attempt_and_aggregate_root(
        conn, import_id="root-cluster", actor_id=101, lease_generation=0
    )
    assert completed["status"] == "completed"
    conn.close()


def test_public_contribution_completion_requires_a_current_resolution():
    import sqlite3

    from app.db.migrations import run_migrations
    from app.services.public_contributions import mark_public_contribution_queue_done

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'contribution-owner', 'x')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status) "
        "VALUES (92, 'https://public.example/92', NULL, 'approved')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question) "
        "VALUES (903, 92, '尚未聚类的题')"
    )
    conn.execute(
        "INSERT INTO public_contribution_requests "
        "(id, source_type, source_id, requester_id, status, snapshot_json) "
        "VALUES (7, 'interview', 1, 7, 'queued', '{}')"
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, ordinal, status, snapshot_json, public_detail_id) "
        "VALUES (71, 7, 'question', 1, 'queued', '{}', 903)"
    )
    conn.execute(
        "INSERT INTO analysis_queue "
        "(id, interview_id, question_detail_id, status, owner_id, contribution_request_id) "
        "VALUES (702, 92, 903, 'done', NULL, 7)"
    )
    conn.commit()

    mark_public_contribution_queue_done(conn, [702])

    item = conn.execute(
        "SELECT status, error_message FROM public_contribution_items WHERE id = 71"
    ).fetchone()
    request_status = conn.execute(
        "SELECT status FROM public_contribution_requests WHERE id = 7"
    ).fetchone()["status"]
    assert item["status"] == "failed"
    assert "resolution" in item["error_message"]
    assert request_status == "failed"
    conn.close()


def test_admin_public_persist_keeps_root_ordinal_and_queue_identity(monkeypatch):
    import sqlite3

    from app.db.migrations import run_migrations
    import app.db.connection as db_connection
    import app.db.operations as db_operations
    import app.services.pipeline.queue as pipeline_queue
    from app.agents.submit.persist_public import persist_public_node

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (201, 'public-admin', 'x', 1)"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES ('admin-root', 201, 'k', 'h', 'share', 'interview', 'v1', "
        "'{\"audit_public_import\":true,\"credential_scope\":\"global\"}', '{}', 'queued')"
    )
    conn.commit()
    monkeypatch.setattr(db_operations, "get_db_connection", lambda: conn)
    monkeypatch.setattr(pipeline_queue, "get_db_connection", lambda: conn)

    async def run_db(function):
        return function()

    monkeypatch.setattr(db_connection, "run_db", run_db)
    monkeypatch.setattr(db_connection, "get_current_job_position", lambda: "后端")

    result = asyncio.run(
        persist_public_node(
            {
                "user_id": 201,
                "is_admin": True,
                "import_id": "admin-root",
                "job_position": "后端",
                "saved_url": "https://public.example/admin-import",
                "extracted_data": {
                    "公司": "示例公司",
                    "面试轮次": "一面",
                    "具体题目清单": ["解释 TCP 三次握手"],
                    "题目 ordinal": [7],
                },
                "tagged_rows": [
                    [
                        "https://public.example/admin-import",
                        "示例公司",
                        "一面",
                        "解释 TCP 三次握手",
                        "网络",
                        "TCP",
                        "握手",
                        "L2-中等",
                    ]
                ],
            }
        )
    )

    detail = conn.execute(
        "SELECT id, import_id, source_ordinal FROM questions_detail WHERE interview_id = ?",
        (result["saved_interview_id"],),
    ).fetchone()
    queue = conn.execute(
        "SELECT root_import_id, question_detail_id, contribution_request_id "
        "FROM analysis_queue WHERE interview_id = ?",
        (result["saved_interview_id"],),
    ).fetchone()
    assert detail["import_id"] == "admin-root"
    assert detail["source_ordinal"] == 7
    assert queue["root_import_id"] == "admin-root"
    assert queue["question_detail_id"] == detail["id"]
    assert queue["contribution_request_id"] is not None
    published = conn.execute(
        "SELECT url, company, round, publish_status FROM interview WHERE id = ?",
        (result["saved_interview_id"],),
    ).fetchone()
    assert tuple(published) == ("", "", "", "pending")
    approval = conn.execute(
        "SELECT status, reviewed_by, review_projection_json FROM public_contribution_requests "
        "WHERE id = ?",
        (queue["contribution_request_id"],),
    ).fetchone()
    assert approval["status"] == "approved_for_processing"
    assert approval["reviewed_by"] == 201
    projection = json.loads(approval["review_projection_json"])
    assert projection["source"]["source_url"] is None
    assert projection["source"]["company"] is None
    checkpoint = conn.execute(
        "SELECT status FROM upload_stage_results WHERE import_id = 'admin-root' "
        "AND stage = 'resolve' AND unit_key = ?",
        (f"detail:{detail['id']}",),
    ).fetchone()
    assert checkpoint["status"] == "pending"
    conn.close()

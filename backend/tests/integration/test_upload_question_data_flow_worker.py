"""AC-029 service/worker trace through real upload and review HTTP routes.

This test does not seed upload intermediates: the submit endpoint, upload
worker, review endpoint, clustering worker and public projection all create
the rows that the assertions trace. Provider calls are deterministic stubs.
The separate Redis/browser deployment leg is intentionally not claimed here.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


QUESTIONS = [
    (10, "Redis AOF 与 RDB 的区别是什么？", "数据库", "Redis", "persistence"),
    (20, "线程池核心线程数和最大线程数如何协作？", "并发", "线程池", "thread-pool"),
    (30, "TCP 三次握手各阶段的状态变化是什么？", "网络", "TCP", "handshake"),
    (40, "MySQL 联合索引最左前缀原则是什么？", "数据库", "MySQL", "index"),
    (50, "分布式锁如何避免误释放？", "分布式", "分布式锁", "lock"),
]

USER_CONFIG = {
    "api_key": "test-user-key",
    "base_url": "https://user-stub.invalid/v1",
    "model": "user-test-model",
    "timeout": 5,
}
GLOBAL_CONFIG = {
    "api_key": "test-system-key",
    "base_url": "https://system-stub.invalid/v1",
    "model": "system-test-model",
    "timeout": 5,
}


@pytest.mark.asyncio
async def test_http_upload_to_personal_and_public_question_trace(client, test_db, monkeypatch):
    """Trace each ordinal through private storage, review, public cluster and retry."""

    import numpy as np
    import app.asgi as asgi_module
    from app.core.auth import get_current_user
    from app.services.credential_preflight import run_credential_preflight
    from app.services.job_lifecycle import CLUSTER_BATCH_JOB_TYPE
    from app.worker import submit_import_task
    from app.worker_cluster_tasks import cluster_batch_task

    for user_id, is_admin in ((101, 0), (102, 0), (201, 1)):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
            "VALUES (?, ?, 'x', ?)",
            (user_id, f"u{user_id}", is_admin),
        )
    test_db.execute(
        "INSERT OR REPLACE INTO user_llm_config (user_id, api_key, base_url, model) "
        "VALUES (101, ?, ?, ?)",
        (USER_CONFIG["api_key"], USER_CONFIG["base_url"], USER_CONFIG["model"]),
    )
    test_db.commit()

    # Keep the HTTP accept path real while making durable jobs runnable by this
    # test instead of relying on an external Redis process.
    monkeypatch.setattr(
        "app.worker.enqueue_submit_import_job",
        AsyncMock(side_effect=RuntimeError("test leaves job in durable outbox")),
    )
    monkeypatch.setattr(
        "app.worker.enqueue_cluster_batch_job",
        AsyncMock(side_effect=RuntimeError("test leaves job in durable outbox")),
    )

    active_user = {"id": 101, "is_admin": 0, "username": "u101"}

    def as_user(user):
        asgi_module.app.dependency_overrides[get_current_user] = lambda: user

    def clear_user():
        asgi_module.app.dependency_overrides.pop(get_current_user, None)

    as_user(active_user)
    try:
        response = client.post(
            "/api/submit-jobs",
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Idempotency-Key": "ac029-real-upload-1",
            },
            data={
                "text": "面经：" + "；".join(question for _, question, *_ in QUESTIONS),
                "target": "share",
                "content_type": "interview",
                "season": "2026春招",
            },
        )
    finally:
        clear_user()
    assert response.status_code == 202, response.text
    import_id = response.json()["import_id"]
    submit_job_id = int(response.json()["job_id"])

    # Execute the real durable preflight job with the user's strict scope.
    preflight = test_db.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? "
        "AND job_type = 'credential_preflight' ORDER BY id DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    assert preflight is not None
    user_probe = run_credential_preflight(
        test_db,
        job_id=int(preflight["id"]),
        probe=lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
    )
    test_db.commit()
    assert user_probe.status == "ok"

    extract_response = json.dumps(
        {
            "type": "interview",
            "data": {
                "公司": "AC029 测试公司",
                "面试轮次": "一面",
                "考察重点": "数据库、并发、网络",
                "难易程度": "中等",
                "具体题目清单": [
                    {"ordinal": ordinal, "question": question}
                    for ordinal, question, *_ in QUESTIONS
                ],
            },
        },
        ensure_ascii=False,
    )

    async def tag_questions(*, url, company, round_, questions, **_kwargs):
        expected = {question: (cat1, cat2, tag) for _, question, cat1, cat2, tag in QUESTIONS}
        return [
            [url, company, round_, question, *expected[question], "中等"]
            for question in questions
        ]

    with patch(
        "app.services.llm._call_llm_with_retry_messages",
        new=AsyncMock(return_value=extract_response),
    ), patch(
        "app.services.llm.get_llm_client_for_user",
        return_value=(MagicMock(), USER_CONFIG["model"], 5, "", "openai"),
    ), patch(
        "app.services.llm._should_use_response_format", return_value=False
    ), patch(
        "app.services.submit_service.tag_questions_batch", new=AsyncMock(side_effect=tag_questions)
    ), patch(
        "app.db.connection.get_taxonomy_for_position",
        return_value={
            "configured": True,
            "categories": [
                {"cat1": cat1, "children": [{"name": cat2}]}
                for _, _, cat1, cat2, _ in QUESTIONS
            ],
        },
    ):
        # Actual upload graph worker; no direct writes to interview/details.
        await submit_import_task({}, submit_job_id)
    test_db.commit()

    private_interview = test_db.execute(
        "SELECT * FROM interview WHERE owner_id = 101 AND status = 'approved' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert private_interview is not None
    private_details = test_db.execute(
        "SELECT id, question, cat1, cat2, tags, source_ordinal, import_id "
        "FROM questions_detail WHERE interview_id = ? ORDER BY source_ordinal",
        (private_interview["id"],),
    ).fetchall()
    assert len(private_details) == len(QUESTIONS)
    assert [row["source_ordinal"] for row in private_details] == [10, 20, 30, 40, 50]
    assert all(row["import_id"] == import_id for row in private_details)
    for row, expected in zip(private_details, QUESTIONS):
        assert tuple(row[key] for key in ("source_ordinal", "question", "cat1", "cat2")) == expected[:4]
        assert expected[4] in row["tags"]

    # Run the real private clustering task so every private detail has a
    # canonical private question and a successful one-to-one resolution.
    public_failure_detail_id = {"value": None}
    public_attempt = {"number": 0}

    async def deterministic_cluster(new_rows, _existing_by_cat2, *, user_id=None, **_kwargs):
        rows = list(new_rows)
        if user_id is None:
            public_attempt["number"] += 1
            if public_attempt["number"] == 1:
                rows = [row for row in rows if int(row["id"]) != public_failure_detail_id["value"]]
        return {
            "matched_to_existing": [],
            "new_clusters": [
                {
                    "ids": [str(row["id"])],
                    "representative": row["question"],
                    "items": [row],
                }
                for row in rows
            ],
        }

    index_manager = MagicMock()
    index_manager.get_all_by_cat2.return_value = {}
    with patch(
        "app.services.pipeline.batch.process_incremental_batch",
        new=AsyncMock(side_effect=deterministic_cluster),
    ), patch(
        "app.services.pipeline.batch.get_index_manager", return_value=index_manager
    ), patch(
        "app.services.embedding_service.encode_texts",
        return_value=np.zeros((0, 3), dtype=np.float32),
    ):
        private_cluster_job = test_db.execute(
            "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = ? "
            "AND status IN ('pending','queued') ORDER BY id DESC LIMIT 1",
            (import_id, CLUSTER_BATCH_JOB_TYPE),
        ).fetchone()
        assert private_cluster_job is not None
        await cluster_batch_task({}, int(private_cluster_job["id"]))
    test_db.commit()

    private_resolution_rows = test_db.execute(
        "SELECT d.source_ordinal, d.cat1, d.cat2, d.tags, r.status, r.canonical_scope, "
        "qb.owner_id, qb.cat1 AS canonical_cat1, qb.cat2 AS canonical_cat2, qb.tags AS canonical_tags "
        "FROM questions_detail d JOIN question_resolutions r ON r.detail_id = d.id "
        "AND r.invalidated_at IS NULL JOIN question_bank qb ON qb.id = r.canonical_id "
        "WHERE d.import_id = ? ORDER BY d.source_ordinal",
        (import_id,),
    ).fetchall()
    assert len(private_resolution_rows) == len(QUESTIONS)
    assert all(row["status"] == "created" for row in private_resolution_rows)
    assert all(row["canonical_scope"] == "private" and row["owner_id"] == 101 for row in private_resolution_rows)
    assert [row["canonical_cat1"] for row in private_resolution_rows] == [q[2] for q in QUESTIONS]
    assert [row["canonical_cat2"] for row in private_resolution_rows] == [q[3] for q in QUESTIONS]
    assert all(q[4] in row["canonical_tags"] for row, q in zip(private_resolution_rows, QUESTIONS))

    contribution = test_db.execute(
        "SELECT id, status FROM public_contribution_requests WHERE requester_id = 101 "
        "AND source_id = ? ORDER BY id DESC LIMIT 1",
        (private_interview["id"],),
    ).fetchone()
    assert contribution is not None and contribution["status"] == "pending_review"
    contribution_items = test_db.execute(
        "SELECT id, ordinal, snapshot_json FROM public_contribution_items "
        "WHERE request_id = ? ORDER BY ordinal",
        (contribution["id"],),
    ).fetchall()
    assert len(contribution_items) == len(QUESTIONS)

    # Real admin approval route: exclude ordinal 50, edit ordinal 10 and redact
    # private source fields before public details are materialized.
    excluded_item_id = int(contribution_items[-1]["id"])
    edited_item_id = int(contribution_items[0]["id"])
    as_user({"id": 201, "is_admin": 1, "username": "u201"})
    try:
        approval_response = client.post(
            f"/api/admin/public-contributions/{contribution['id']}/approve",
            json={
                "expected_revision": 1,
                "excluded_item_ids": [excluded_item_id],
                "review_fields": {
                    "source": {"company": None, "source_url": None},
                    "items": [
                        {
                            "item_id": edited_item_id,
                            "question": "已审核编辑：Redis AOF 与 RDB 的区别是什么？",
                        }
                    ],
                },
            },
        )
    finally:
        clear_user()
    assert approval_response.status_code == 200, approval_response.text
    public_interview_id = int(approval_response.json()["public_interview_id"])

    public_items = test_db.execute(
        "SELECT i.id, i.ordinal, i.status, i.public_detail_id, d.question, "
        "d.cat1, d.cat2, d.tags, d.source_ordinal "
        "FROM public_contribution_items i LEFT JOIN questions_detail d "
        "ON d.id = i.public_detail_id WHERE i.request_id = ? ORDER BY i.ordinal",
        (contribution["id"],),
    ).fetchall()
    retained = [item for item in public_items if item["status"] != "rejected"]
    assert len(retained) == 4
    assert all(item["public_detail_id"] for item in retained)
    assert retained[0]["question"] == "已审核编辑：Redis AOF 与 RDB 的区别是什么？"
    assert retained[-1]["source_ordinal"] == 40
    ordinal_trace = test_db.execute(
        "SELECT source.source_ordinal AS private_ordinal, public.source_ordinal AS public_ordinal "
        "FROM public_contribution_items item "
        "JOIN questions_detail source ON source.id = item.source_item_id "
        "JOIN questions_detail public ON public.id = item.public_detail_id "
        "WHERE item.request_id = ? AND item.status != 'rejected' ORDER BY item.ordinal",
        (contribution["id"],),
    ).fetchall()
    assert [tuple(row) for row in ordinal_trace] == [
        (10, 10), (20, 20), (30, 30), (40, 40)
    ]
    public_failure_detail_id["value"] = int(retained[1]["public_detail_id"])

    public_interview = test_db.execute(
        "SELECT company, url FROM interview WHERE id = ?", (public_interview_id,)
    ).fetchone()
    assert public_interview["company"] in (None, "")
    assert public_interview["url"] in (None, "")

    # Fresh system-scope probe is required after review. Run it using the
    # durable preflight job created by the admin approval endpoint.
    global_preflight = test_db.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight' "
        "ORDER BY id DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    assert global_preflight is not None
    monkeypatch.setattr(
        "app.services.upload_credentials._default_global_loader",
        lambda: GLOBAL_CONFIG,
    )
    global_probe = run_credential_preflight(
        test_db,
        job_id=int(global_preflight["id"]),
        probe=lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
        global_config_loader=lambda: GLOBAL_CONFIG,
    )
    test_db.commit()
    assert global_probe.status == "ok"

    def run_one_pending_cluster_job():
        job = test_db.execute(
            "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = ? "
            "AND status IN ('pending','queued') ORDER BY id DESC LIMIT 1",
            (import_id, CLUSTER_BATCH_JOB_TYPE),
        ).fetchone()
        assert job is not None
        return job["id"]

    # First public attempt deliberately omits one detail from the model result.
    # The real writer must preserve successes and mark that exact ordinal failed.
    with patch(
        "app.services.pipeline.batch.process_incremental_batch",
        new=AsyncMock(side_effect=deterministic_cluster),
    ), patch(
        "app.services.pipeline.batch.get_index_manager", return_value=index_manager
    ), patch(
        "app.services.embedding_service.encode_texts",
        return_value=np.zeros((0, 3), dtype=np.float32),
    ):
        await cluster_batch_task({}, int(run_one_pending_cluster_job()))
    test_db.commit()

    failed_detail = public_failure_detail_id["value"]
    first_public_success_ids = {
        int(row[0])
        for row in test_db.execute(
            "SELECT canonical_id FROM question_resolutions r "
            "JOIN public_contribution_items i ON i.public_detail_id = r.detail_id "
            "WHERE i.request_id = ? AND i.status = 'published' AND r.invalidated_at IS NULL",
            (contribution["id"],),
        ).fetchall()
    }
    failed_item = test_db.execute(
        "SELECT status FROM public_contribution_items WHERE request_id = ? AND public_detail_id = ?",
        (contribution["id"], failed_detail),
    ).fetchone()
    assert failed_item["status"] == "failed"
    assert len(first_public_success_ids) == 3
    failed_root = test_db.execute(
        "SELECT status FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert failed_root["status"] != "completed", "一题失败时 root 不得提前完成"

    # Retry through the real admin endpoint; only the failed child is requeued,
    # a new global preflight is required, and prior canonical ids stay intact.
    as_user({"id": 201, "is_admin": 1, "username": "u201"})
    try:
        retry_response = client.post(
            f"/api/admin/public-contributions/{contribution['id']}/retry",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    finally:
        clear_user()
    assert retry_response.status_code == 200, retry_response.text
    second_preflight = test_db.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'credential_preflight' "
        "ORDER BY id DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    assert int(second_preflight["id"]) > int(global_preflight["id"])
    retry_probe = run_credential_preflight(
        test_db,
        job_id=int(second_preflight["id"]),
        probe=lambda credential: {
            "status": "ok",
            "provider": credential.provider,
            "model": credential.model,
            "latency_ms": 1,
        },
        global_config_loader=lambda: GLOBAL_CONFIG,
    )
    test_db.commit()
    assert retry_probe.status == "ok"
    with patch(
        "app.services.pipeline.batch.process_incremental_batch",
        new=AsyncMock(side_effect=deterministic_cluster),
    ), patch(
        "app.services.pipeline.batch.get_index_manager", return_value=index_manager
    ), patch(
        "app.services.embedding_service.encode_texts",
        return_value=np.zeros((0, 3), dtype=np.float32),
    ):
        await cluster_batch_task({}, int(run_one_pending_cluster_job()))
    test_db.commit()

    final_public_rows = test_db.execute(
        "SELECT i.ordinal, i.status, d.question, d.source_ordinal, r.status AS resolution_status, "
        "qb.owner_id, qb.cat1, qb.cat2, qb.tags "
        "FROM public_contribution_items i JOIN questions_detail d ON d.id = i.public_detail_id "
        "JOIN question_resolutions r ON r.detail_id = d.id AND r.invalidated_at IS NULL "
        "JOIN question_bank qb ON qb.id = r.canonical_id "
        "WHERE i.request_id = ? AND i.status = 'published' ORDER BY i.ordinal",
        (contribution["id"],),
    ).fetchall()
    assert len(final_public_rows) == 4
    assert all(row["resolution_status"] in ("created", "matched") for row in final_public_rows)
    assert all(row["owner_id"] is None for row in final_public_rows)
    assert [row["source_ordinal"] for row in final_public_rows] == [10, 20, 30, 40]
    assert final_public_rows[0]["question"].startswith("已审核编辑：")
    assert "分布式锁如何避免误释放" not in "\n".join(row["question"] for row in final_public_rows)
    for row in final_public_rows:
        expected = next(question for question in QUESTIONS if question[0] == row["source_ordinal"])
        assert (row["cat1"], row["cat2"]) == expected[2:4]
        assert expected[4] in row["tags"]
    assert {
        int(row["canonical_id"])
        for row in test_db.execute(
            "SELECT r.canonical_id FROM question_resolutions r "
            "JOIN public_contribution_items i ON i.public_detail_id = r.detail_id "
            "WHERE i.request_id = ? AND i.status = 'published' AND r.invalidated_at IS NULL",
            (contribution["id"],),
        ).fetchall()
    } == first_public_success_ids | {
        int(
            test_db.execute(
                "SELECT canonical_id FROM question_resolutions "
                "WHERE detail_id = ? AND invalidated_at IS NULL",
                (failed_detail,),
            ).fetchone()[0]
        )
    }

    # Authorized public APIs agree with the traced database projection.
    monkeypatch.setattr("app.routers.questions.get_master_bank_cache", AsyncMock(return_value=None))
    monkeypatch.setattr("app.routers.questions.set_master_bank_cache", AsyncMock())
    as_user(active_user)
    try:
        public_bank = client.get("/api/master-bank?filter=public&page_size=100").json()
        personal_bank = client.get("/api/master-bank?filter=mine&page_size=100").json()
        experiences = client.get("/api/interview/experiences").json()["data"]
    finally:
        clear_user()
    public_questions = [item for item in public_bank["items"] if item["id"] in {
        int(row[0]) for row in test_db.execute(
            "SELECT r.canonical_id FROM question_resolutions r "
            "JOIN public_contribution_items i ON i.public_detail_id = r.detail_id "
            "WHERE i.request_id = ? AND i.status = 'published' AND r.invalidated_at IS NULL",
            (contribution["id"],),
        ).fetchall()
    }]
    assert len(public_questions) == 4
    assert len([item for item in personal_bank["items"] if item["owner_id"] == 101]) == 5
    assert any(item["id"] == public_interview_id and item["question_count"] == 4 for item in experiences)

    as_user({"id": 102, "is_admin": 0, "username": "u102"})
    try:
        other_user_bank = client.get("/api/master-bank?filter=mine&page_size=100").json()
    finally:
        clear_user()
    assert not any(item["owner_id"] == 101 for item in other_user_bank["items"])

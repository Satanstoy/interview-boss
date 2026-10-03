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
    "api_format": "chat",
}
GLOBAL_CONFIG = {
    "api_key": "test-system-key",
    "base_url": "https://system-stub.invalid/v1",
    "model": "system-test-model",
    "timeout": 5,
    "api_format": "chat",
}


@pytest.mark.asyncio
async def test_http_upload_to_personal_and_public_question_trace(
    client, test_db, monkeypatch, tmp_path
):
    """Trace each ordinal through private storage, review, public cluster and retry."""

    import numpy as np
    import app.asgi as asgi_module
    from app.core.auth import get_current_user
    from app.db.queries import get_user_job_position
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
        "INSERT OR REPLACE INTO user_llm_config (user_id, api_key, base_url, model, api_format) "
        "VALUES (101, ?, ?, ?, ?)",
        (
            USER_CONFIG["api_key"],
            USER_CONFIG["base_url"],
            USER_CONFIG["model"],
            USER_CONFIG["api_format"],
        ),
    )
    for key, value in (
        ("llm_api_key", GLOBAL_CONFIG["api_key"]),
        ("llm_base_url", GLOBAL_CONFIG["base_url"]),
        ("llm_model", GLOBAL_CONFIG["model"]),
        ("llm_api_format", GLOBAL_CONFIG["api_format"]),
    ):
        test_db.execute(
            "INSERT OR REPLACE INTO user_profile (key, value) VALUES (?, ?)",
            (key, value),
        )
    position_id, position_name = get_user_job_position(101)
    existing_public_question = QUESTIONS[1][1]
    existing_public_sources = [{
        "url": "https://public.example/existing",
        "company": "Existing Public Company",
        "round": "一面",
    }]
    test_db.execute(
        "INSERT INTO question_bank (question, cat1, cat2, tags, frequency, sources, "
        "original_questions, original_question_sources, owner_id, status, job_position) "
        "VALUES (?, ?, ?, ?, 1, ?, ?, ?, NULL, 'approved', ?)",
        (
            existing_public_question,
            QUESTIONS[1][2],
            QUESTIONS[1][3],
            QUESTIONS[1][4],
            json.dumps(existing_public_sources, ensure_ascii=False),
            json.dumps([existing_public_question], ensure_ascii=False),
            json.dumps(
                [{"question": existing_public_question, "sources": existing_public_sources}],
                ensure_ascii=False,
            ),
            position_name,
        ),
    )
    existing_public_canonical_id = int(
        test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    )
    if position_id:
        test_db.execute(
            "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
            (existing_public_canonical_id, position_id),
        )
    test_db.commit()

    # Keep the HTTP accept path real while making durable jobs runnable by this
    # test instead of relying on an external Redis process.
    monkeypatch.setattr(
        "app.worker_enqueue.enqueue_submit_import_job",
        AsyncMock(side_effect=RuntimeError("test leaves job in durable outbox")),
    )
    monkeypatch.setattr(
        "app.worker_enqueue.enqueue_credential_preflight_job",
        AsyncMock(side_effect=RuntimeError("test leaves preflight in durable outbox")),
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

    # Execute both real durable preflight jobs with their own strict scopes.
    preflights = test_db.execute(
        "SELECT j.id, p.payload FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' ORDER BY j.id",
        (import_id,),
    ).fetchall()
    assert len(preflights) == 2
    for preflight in preflights:
        scope = json.loads(preflight["payload"])["credential_scope"]
        outcome = run_credential_preflight(
            test_db,
            job_id=int(preflight["id"]),
            probe=lambda credential: {
                "status": "ok",
                "provider": credential.provider,
                "model": credential.model,
                "latency_ms": 1,
            },
        )
        assert outcome.status == "ok", f"{scope} scope must pass before extraction"
    test_db.commit()
    submit_job = test_db.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
        (import_id,),
    ).fetchone()
    assert submit_job is not None
    submit_job_id = int(submit_job["id"])
    assert not test_db.in_transaction, "accept/preflight should leave the test connection committed"

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
    tag_response = json.dumps(
        {
            "questions": [
                {
                    "id": index,
                    "题目": question,
                    "一级大类": cat1,
                    "二级子类": cat2,
                    "考点标签": tag,
                    "难度标签": "L2-中等",
                }
                for index, (_, question, cat1, cat2, tag) in enumerate(QUESTIONS)
            ]
        },
        ensure_ascii=False,
    )
    match_response = json.dumps(
        {
            "matches": [{"new_id": 1, "cluster_id": existing_public_canonical_id}],
            "unmatched": [],
        },
        ensure_ascii=False,
    )
    provider_responses = []
    for content in (extract_response, tag_response, match_response):
        provider_response = MagicMock()
        provider_response.choices = [MagicMock(message=MagicMock(content=content))]
        provider_response.usage = MagicMock(prompt_tokens=37, completion_tokens=29)
        provider_responses.append(provider_response)
    fake_llm_client = MagicMock()
    fake_llm_client.chat.completions.create = AsyncMock(
        side_effect=provider_responses
    )

    with patch(
        "app.services.llm._make_client", return_value=fake_llm_client
    ), patch(
        "app.services.llm._should_use_response_format", return_value=False
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

    extract_calls = test_db.execute(
        "SELECT credential_scope, payer_type, payer_user_id, provider, model, api_format, "
        "config_fingerprint, status, input_tokens, output_tokens FROM upload_llm_calls "
        "WHERE root_import_id = ? AND stage = 'extract'",
        (import_id,),
    ).fetchall()
    assert len(extract_calls) == 1, "实际提取请求必须进入上传调用账本"
    extract_call = extract_calls[0]
    assert tuple(extract_call) == (
        "user",
        "user",
        101,
        "openai",
        USER_CONFIG["model"],
        "chat",
        extract_call["config_fingerprint"],
        "succeeded",
        37,
        29,
    )
    assert extract_call["config_fingerprint"]

    classify_calls = test_db.execute(
        "SELECT credential_scope, payer_type, payer_user_id, provider, model, api_format, "
        "config_fingerprint, status "
        "FROM upload_llm_calls WHERE root_import_id = ? AND stage = 'classify'",
        (import_id,),
    ).fetchall()
    assert len(classify_calls) == 1
    assert tuple(classify_calls[0]) == (
        "user",
        "user",
        101,
        "openai",
        USER_CONFIG["model"],
        "chat",
        classify_calls[0]["config_fingerprint"],
        "succeeded",
    )
    assert classify_calls[0]["config_fingerprint"]

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

    # Run the real private clustering task. One detail has already matched the
    # public canonical during private preprocessing and must not be copied or
    # mutate public source/count fields before the user approves the share.
    public_failure_detail_id = {"value": None}
    public_attempt = {"number": 0}

    async def deterministic_cluster(new_rows, _existing_by_cat2, *, user_id=None, **_kwargs):
        rows = list(new_rows)
        matched = []
        if user_id is None:
            public_attempt["number"] += 1
            if public_attempt["number"] == 1:
                rows = [row for row in rows if int(row["id"]) != public_failure_detail_id["value"]]
            matched_rows = [
                row for row in rows if row["question"] == existing_public_question
            ]
            for row in matched_rows:
                matched.append(
                    {
                        "qd_id": int(row["id"]),
                        "cluster_id": existing_public_canonical_id,
                        "question": row["question"],
                        "cat1": row["cat1"],
                        "cat2": row["cat2"],
                        "tags": row["tags"],
                        "diff_tag": row["diff_tag"],
                        "url": row["url"],
                        "company": row["company"],
                        "round": row["round"],
                    }
                )
            matched_ids = {int(row["id"]) for row in matched_rows}
            rows = [row for row in rows if int(row["id"]) not in matched_ids]
        return {
            "matched_to_existing": matched,
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

    private_scope_lease = test_db.execute(
        "SELECT scope_key, generation, holder_token FROM upload_scope_leases "
        "ORDER BY scope_key LIMIT 1"
    ).fetchone()
    assert private_scope_lease is not None, "上传私有聚类必须持有scope lease"
    assert private_scope_lease["generation"] >= 1
    assert private_scope_lease["holder_token"] is None, "聚类结束后必须释放scope lease"

    private_resolution_rows = test_db.execute(
        "SELECT d.source_ordinal, d.cat1, d.cat2, d.tags, r.status, r.reason, r.canonical_scope, "
        "qb.id AS canonical_id, "
        "qb.owner_id, qb.cat1 AS canonical_cat1, qb.cat2 AS canonical_cat2, qb.tags AS canonical_tags "
        "FROM questions_detail d LEFT JOIN question_resolutions r ON r.detail_id = d.id "
        "AND r.invalidated_at IS NULL LEFT JOIN question_bank qb ON qb.id = r.canonical_id "
        "WHERE d.import_id = ? ORDER BY d.source_ordinal",
        (import_id,),
    ).fetchall()
    assert len(private_resolution_rows) == len(QUESTIONS)
    public_hit = private_resolution_rows[1]
    assert public_hit["status"] == "matched", public_hit["reason"]
    assert public_hit["canonical_scope"] == "public"
    assert public_hit["canonical_id"] == existing_public_canonical_id
    assert public_hit["owner_id"] is None
    private_created = [row for row in private_resolution_rows if row["source_ordinal"] != 20]
    assert all(row["status"] == "created" for row in private_created)
    assert all(row["canonical_scope"] == "private" and row["owner_id"] == 101 for row in private_created)
    assert [row["canonical_cat1"] for row in private_resolution_rows] == [q[2] for q in QUESTIONS]
    assert [row["canonical_cat2"] for row in private_resolution_rows] == [q[3] for q in QUESTIONS]
    assert all(q[4] in row["canonical_tags"] for row, q in zip(private_resolution_rows, QUESTIONS))
    unchanged_public = test_db.execute(
        "SELECT frequency, sources, original_questions, original_question_sources "
        "FROM question_bank WHERE id = ?",
        (existing_public_canonical_id,),
    ).fetchone()
    assert tuple(unchanged_public) == (
        1,
        json.dumps(existing_public_sources, ensure_ascii=False),
        json.dumps([existing_public_question], ensure_ascii=False),
        json.dumps(
            [{"question": existing_public_question, "sources": existing_public_sources}],
            ensure_ascii=False,
        ),
    )

    preserved_private_canonical_id = int(private_resolution_rows[0]["canonical_id"])
    test_db.execute(
        "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, score) "
        "VALUES (101, ?, '保留的个人练习答案', 88)",
        (preserved_private_canonical_id,),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency) "
        "VALUES (101, ?, 'review', 4)",
        (preserved_private_canonical_id,),
    )

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

    promoted_occurrences = test_db.execute(
        "SELECT source.source_ordinal, current_resolution.canonical_scope, "
        "current_resolution.status, current_resolution.canonical_id, "
        "public_resolution.canonical_id AS public_canonical_id, private_canonical.deleted_at "
        "FROM public_contribution_items item "
        "JOIN questions_detail source ON source.id = item.source_item_id "
        "JOIN question_resolutions current_resolution ON current_resolution.detail_id = source.id "
        "AND current_resolution.invalidated_at IS NULL "
        "JOIN question_resolutions public_resolution ON public_resolution.detail_id = item.public_detail_id "
        "AND public_resolution.invalidated_at IS NULL "
        "LEFT JOIN question_bank private_canonical ON private_canonical.id = ("
        "  SELECT old_resolution.canonical_id FROM question_resolutions old_resolution "
        "  WHERE old_resolution.detail_id = source.id AND old_resolution.canonical_scope = 'private' "
        "  ORDER BY old_resolution.id DESC LIMIT 1) "
        "WHERE item.request_id = ? AND item.status = 'published' ORDER BY source.source_ordinal",
        (contribution["id"],),
    ).fetchall()
    assert len(promoted_occurrences) == 4
    assert all(row["canonical_scope"] == "public" for row in promoted_occurrences)
    assert all(row["status"] == "matched" for row in promoted_occurrences)
    assert all(row["canonical_id"] == row["public_canonical_id"] for row in promoted_occurrences)
    assert next(row for row in promoted_occurrences if row["source_ordinal"] == 20)["deleted_at"] is None
    assert all(
        row["deleted_at"] is not None
        for row in promoted_occurrences
        if row["source_ordinal"] != 20
    )
    assert tuple(test_db.execute(
        "SELECT user_answer, score FROM user_practice_history "
        "WHERE user_id = 101 AND question_bank_id = ?",
        (preserved_private_canonical_id,),
    ).fetchone()) == ("保留的个人练习答案", 88)
    assert tuple(test_db.execute(
        "SELECT state, proficiency FROM user_question_review "
        "WHERE user_id = 101 AND question_bank_id = ?",
        (preserved_private_canonical_id,),
    ).fetchone()) == ("review", 4)
    public_scope_lease = test_db.execute(
        "SELECT scope_key, generation, holder_token FROM upload_scope_leases "
        "WHERE scope_key LIKE '%:public' ORDER BY scope_key LIMIT 1"
    ).fetchone()
    assert public_scope_lease is not None
    assert public_scope_lease["generation"] >= 2, "公共失败重试必须重新取得新代次scope lease"
    assert public_scope_lease["holder_token"] is None
    for row in final_public_rows:
        expected = next(question for question in QUESTIONS if question[0] == row["source_ordinal"])
        assert (row["cat1"], row["cat2"]) == expected[2:4]
        assert expected[4] in row["tags"]
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
    assert len([item for item in personal_bank["items"] if item["owner_id"] == 101]) == 1
    assert any(item["id"] == public_interview_id and item["question_count"] == 4 for item in experiences)

    as_user({"id": 102, "is_admin": 0, "username": "u102"})
    try:
        other_user_bank = client.get("/api/master-bank?filter=mine&page_size=100").json()
    finally:
        clear_user()
    assert not any(item["owner_id"] == 101 for item in other_user_bank["items"])

    # AC-029 trace artifact contains stable test IDs/statuses, never source
    # material or model credentials. One row covers every input ordinal,
    # including the item excluded from the public projection.
    trace_rows = test_db.execute(
        "SELECT source.source_ordinal, source.id AS private_detail_id, "
        "private_resolution.id AS private_resolution_id, "
        "private_resolution.canonical_id AS private_stage_canonical_id, "
        "private_resolution.canonical_scope AS private_stage_canonical_scope, "
        "item.id AS contribution_item_id, item.status AS contribution_status, "
        "item.public_detail_id, public_detail.id AS materialized_public_detail_id, "
        "public_resolution.id AS public_resolution_id, "
        "public_resolution.canonical_id AS public_canonical_id, "
        "public_resolution.status AS public_resolution_status "
        "FROM questions_detail source "
        "LEFT JOIN question_resolutions private_resolution "
        "ON private_resolution.detail_id = source.id "
        "AND private_resolution.invalidated_at IS NULL "
        "LEFT JOIN public_contribution_items item "
        "ON item.request_id = ? AND item.source_item_id = source.id "
        "LEFT JOIN questions_detail public_detail ON public_detail.id = item.public_detail_id "
        "LEFT JOIN question_resolutions public_resolution "
        "ON public_resolution.detail_id = public_detail.id "
        "AND public_resolution.invalidated_at IS NULL "
        "WHERE source.import_id = ? ORDER BY source.source_ordinal",
        (contribution["id"], import_id),
    ).fetchall()
    assert len(trace_rows) == len(QUESTIONS)
    stage_rows = test_db.execute(
        "SELECT id, stage, unit_key, status FROM upload_stage_results WHERE import_id = ? "
        "ORDER BY id",
        (import_id,),
    ).fetchall()
    stage_trace = [
        {
            "id": int(row["id"]),
            "stage": row["stage"],
            "unit_key": row["unit_key"],
            "status": row["status"],
        }
        for row in stage_rows
    ]
    review = test_db.execute(
        "SELECT revision, projection_hash, review_projection_json "
        "FROM public_contribution_requests WHERE id = ?",
        (contribution["id"],),
    ).fetchone()
    projection = json.loads(review["review_projection_json"] or "{}")
    projection_source = projection.get("source") or {}
    trace_items = []
    for row, expected in zip(trace_rows, QUESTIONS):
        ordinal = int(row["source_ordinal"])
        assert ordinal == expected[0]
        is_excluded = ordinal == 50
        related_detail_units = {
            f"detail:{int(row['private_detail_id'])}",
            f"detail:{int(row['public_detail_id'])}" if row["public_detail_id"] else None,
        }
        item_stages = [
            stage for stage in stage_trace
            if stage["stage"] != "resolve"
            or not stage["unit_key"].startswith("detail:")
            or stage["unit_key"] in related_detail_units
        ]
        assert bool(row["materialized_public_detail_id"]) is (not is_excluded)
        if not is_excluded:
            assert row["public_resolution_id"] is not None
            assert row["public_canonical_id"] is not None
            assert row["contribution_status"] == "published"
        trace_items.append(
            {
                "input_ordinal": ordinal,
                "expected_category": [expected[2], expected[3]],
                "stages": item_stages,
                "private_detail_id": int(row["private_detail_id"]),
                "private_resolution_id": int(row["private_resolution_id"]),
                "private_stage_canonical_id": int(row["private_stage_canonical_id"]),
                "private_stage_canonical_scope": row["private_stage_canonical_scope"],
                "contribution_item_id": int(row["contribution_item_id"]),
                "contribution_status": row["contribution_status"],
                "review_projection": {
                    "revision": int(review["revision"]),
                    "hash": review["projection_hash"],
                    "source_company_redacted": projection_source.get("company") is None,
                    "source_url_redacted": projection_source.get("source_url") is None,
                    "excluded": is_excluded,
                },
                "public_detail_id": (
                    int(row["materialized_public_detail_id"])
                    if row["materialized_public_detail_id"]
                    else None
                ),
                "public_resolution_id": (
                    int(row["public_resolution_id"])
                    if row["public_resolution_id"]
                    else None
                ),
                "public_canonical_id": (
                    int(row["public_canonical_id"])
                    if row["public_canonical_id"]
                    else None
                ),
                "public_resolution_status": row["public_resolution_status"],
            }
        )
    trace_path = tmp_path / "ac029-question-trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "import_id": str(import_id),
                "contribution_request_id": int(contribution["id"]),
                "stages": stage_trace,
                "items": trace_items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    written_trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert [item["input_ordinal"] for item in written_trace["items"]] == [10, 20, 30, 40, 50]
    required_stages = {"extract", "classify", "persist", "resolve"}
    recorded_stages = {stage["stage"] for stage in stage_trace}
    assert not recorded_stages.intersection(
        {"preflight", "complete", "fill", "tag", "match", "save", "cluster"}
    )
    for item in written_trace["items"]:
        stage_refs = item["stages"]
        assert required_stages <= {stage["stage"] for stage in stage_refs}
        assert all(stage["id"] and stage["unit_key"] and stage["status"] for stage in stage_refs)
        private_unit = f"detail:{item['private_detail_id']}"
        assert private_unit in {
            stage["unit_key"] for stage in stage_refs if stage["stage"] == "resolve"
        }
        if item["public_detail_id"]:
            assert f"detail:{item['public_detail_id']}" in {
                stage["unit_key"] for stage in stage_refs if stage["stage"] == "resolve"
            }
    assert "test-user-key" not in trace_path.read_text(encoding="utf-8")
    assert "test-system-key" not in trace_path.read_text(encoding="utf-8")

    # AC-007 血缘：v2 上传产生的每一条队列行都必须带 root_import_id。
    # 私人路径显式传 root，公共路径靠 contribution_request_id → upload_imports 回填；
    # 缺失会让对账无法按 root 续调（AC-012 桶调度按 root 聚合）。
    orphan_queue_rows = test_db.execute(
        "SELECT COUNT(*) FROM analysis_queue WHERE root_import_id IS NULL"
    ).fetchone()[0]
    assert orphan_queue_rows == 0, (
        "v2 上传的队列行缺少 root_import_id（血缘断裂，对账无法按 root 续调）"
    )
    linked_queue_rows = test_db.execute(
        "SELECT DISTINCT root_import_id FROM analysis_queue"
    ).fetchall()
    assert [str(row["root_import_id"]) for row in linked_queue_rows] == [str(import_id)]


@pytest.mark.asyncio
async def test_admin_public_import_persists_approved_projection_audit(
    client, test_db
):
    """AC-003: 管理员显式公共导入要留下可追溯的批准投影。"""

    from app.agents.submit.persist_public import persist_public_node

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (201, 'admin-201', 'x', 1)"
    )
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, status) "
        "VALUES ('imp-admin-public', 201, 'admin-public-1', 'hash-admin-public', 'share', "
        "'interview', 'v1', '{\"audit_public_import\":true}', '{}', 'queued')"
    )
    test_db.commit()

    result = await persist_public_node(
        {
            "extracted_data": {
                "公司": "AC 审计公司",
                "面试轮次": "一面",
                "具体题目清单": ["事务隔离级别有哪些？"],
            },
            "tagged_rows": [
                [
                    "internal://admin-public",
                    "AC 审计公司",
                    "一面",
                    "事务隔离级别有哪些？",
                    "数据库",
                    "事务",
                    "ACID",
                    "中等",
                ]
            ],
            "job_position": "后端开发",
            "saved_url": "internal://admin-public",
            "season": "2026 秋招",
            "user_id": 201,
            "is_admin": True,
            "import_id": "imp-admin-public",
        }
    )
    test_db.commit()

    audit = test_db.execute(
        "SELECT id, status, reviewed_by, review_projection_json "
        "FROM public_contribution_requests WHERE requester_id = 201 "
        "AND source_id = ? ORDER BY id DESC LIMIT 1",
        (result["saved_interview_id"],),
    ).fetchone()
    assert audit is not None, "管理员公共直导必须创建持久化批准记录"
    assert audit["status"] == "approved_for_processing"
    assert audit["reviewed_by"] == 201
    projection = json.loads(audit["review_projection_json"])
    assert projection["source"]["company"] is None
    assert projection["source"]["round"] is None
    assert projection["source"]["source_url"] is None
    assert projection["items"][0]["question"] == "事务隔离级别有哪些？"

    interview = test_db.execute(
        "SELECT url, company, round, publish_status FROM interview WHERE id = ?",
        (result["saved_interview_id"],),
    ).fetchone()
    assert tuple(interview) == ("", "", "", "pending")

    event = test_db.execute(
        "SELECT actor_id, action, to_status, metadata_json "
        "FROM public_contribution_events WHERE request_id = ? ORDER BY id DESC LIMIT 1",
        (audit["id"],),
    ).fetchone()
    assert event is not None
    assert (event["actor_id"], event["action"], event["to_status"]) == (
        201,
        "admin_import_approved",
        "approved_for_processing",
    )
    assert json.loads(event["metadata_json"])["import_id"] == "imp-admin-public"

    root_link = test_db.execute(
        "SELECT contribution_request_id FROM upload_imports WHERE id = ?",
        ("imp-admin-public",),
    ).fetchone()
    assert root_link["contribution_request_id"] == audit["id"]

    queue_link = test_db.execute(
        "SELECT COUNT(*) FROM analysis_queue WHERE interview_id = ? "
        "AND contribution_request_id = ? AND root_import_id = ?",
        (result["saved_interview_id"], audit["id"], "imp-admin-public"),
    ).fetchone()[0]
    assert queue_link == 1

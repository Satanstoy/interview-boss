"""AC-006 / UR-006：match_outcomes 三态在真实节点上的行为。

- failed（模型 401/超时/结构错误）→ 该题不进聚类队列、不建 canonical、
  resolution 记 failed（可恢复）；
- 只有真正无候选的 no_match 才允许创建同 scope 题。

本文件原先被 ``UPLOAD_TEST_DB_PATH`` 门禁整体 skip（等于 AC-006 从未验收）。
节点本身走标准 ``test_db`` fixture 的隔离内存库，无需外部环境变量。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

TAGGED_ROWS = [
    ["https://test.com/1", "字节", "一面", "TCP握手", "数据库", "Redis", "缓存", "L2-中等"],
    ["https://test.com/2", "字节", "二面", "Redis持久化", "数据库", "Redis", "持久化", "L2-中等"],
]

EXTRACTED_DATA = {
    "公司": "字节",
    "面试轮次": "一面",
    "具体题目清单": ["TCP握手", "Redis持久化"],
}

# new_id 0 = 模型失败（failed）；new_id 1 = 个人池无匹配（no_match）
OUTCOMES = {
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


def _seed_user(test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (1, 'u1', 'x', 1)"
    )
    test_db.commit()


def test_node_match_outcomes_three_state_honors_failure_without_new_canonical(test_db):
    """失败题不得入队；no_match 真新题正常入队。"""

    from app.agents.submit.persist_personal import match_and_persist_personal_node

    _seed_user(test_db)
    with (
        patch("app.services.clustering.match_outcomes", AsyncMock(return_value=OUTCOMES)),
        patch("app.db.connection.get_current_job_position", return_value="后端开发"),
        patch(
            "app.services.pipeline.queue._run_cluster_batch_in_background",
            AsyncMock(return_value=False),
        ),
    ):
        result = asyncio.run(
            match_and_persist_personal_node(
                {
                    "extracted_data": EXTRACTED_DATA,
                    "tagged_rows": TAGGED_ROWS,
                    "saved_url": "https://test.com/1",
                    "season": "2027届",
                    "user_id": 1,
                    "is_admin": True,
                    "job_position": "后端开发",
                }
            )
        )

    details = {row["question"]: row["id"] for row in test_db.execute("SELECT id,question FROM questions_detail")}
    enqueued = {row[0] for row in test_db.execute("SELECT question_detail_id FROM analysis_queue")}
    assert details["TCP握手"] not in enqueued, "模型失败不能进入聚类队列"
    assert details["Redis持久化"] in enqueued, "真正无匹配的题应进入聚类队列"
    assert result["match_failed"] == 1


def test_failed_question_never_reaches_the_personal_queue(test_db):
    """AC-006/AC-019：失败的题不得进入个人聚类队列，no_match 的题必须进入。

    个人上传的新 canonical 由 durable 分析队列（cluster worker）创建
    （``persist_unmatched=False``，见 ``db/operations._apply_incremental_txn``），
    所以这里断言的是队列内容而不是同步落库结果：失败的题一旦入队，
    异步聚类就会为它建出错误的新题。
    """

    from app.agents.submit.persist_personal import match_and_persist_personal_node

    _seed_user(test_db)

    with (
        patch("app.services.clustering.match_outcomes", AsyncMock(return_value=OUTCOMES)),
        patch("app.db.connection.get_current_job_position", return_value="后端开发"),
        patch(
            "app.services.pipeline.queue._run_cluster_batch_in_background",
            AsyncMock(return_value=False),
        ),
    ):
        result = asyncio.run(
            match_and_persist_personal_node(
                {
                    "extracted_data": EXTRACTED_DATA,
                    "tagged_rows": TAGGED_ROWS,
                    "saved_url": "https://test.com/1",
                    "season": "2027届",
                    "user_id": 1,
                    "is_admin": True,
                    "job_position": "后端开发",
                }
            )
        )

    details = test_db.execute(
        "SELECT id, question FROM questions_detail ORDER BY id"
    ).fetchall()
    assert len(details) == 2, "两行明细都必须落库（不静默丢题）"
    # 无 import_id 上下文时 source_ordinal 由 link_details_to_import 写入，
    # 这里按题面定位明细。
    by_question = {row["question"]: int(row["id"]) for row in details}

    queued_detail_ids = {
        int(row["question_detail_id"])
        for row in test_db.execute(
            "SELECT question_detail_id FROM analysis_queue WHERE status = 'pending'"
        ).fetchall()
    }
    # TCP握手 = new_id 0（模型失败）→ 不得入队，否则异步会为它建新 canonical
    assert by_question["TCP握手"] not in queued_detail_ids, (
        "匹配失败的题绝不能进入聚类队列异步建新题，AC-006"
    )
    # Redis持久化 = new_id 1（真无候选）→ 必须入队，由队列创建同 scope 新题
    assert by_question["Redis持久化"] in queued_detail_ids, (
        "no_match 真新题必须进入聚类队列"
    )

    assert test_db.execute(
        "SELECT COUNT(*) FROM question_bank WHERE owner_id = 1"
    ).fetchone()[0] == 0, (
        "个人新 canonical 由队列创建；节点同步不得提前建题"
    )
    assert result["match_failed"] == 1


def test_retry_after_eight_of_ten_answers_failed_requeues_only_failed_questions(
    test_db,
):
    """AC-011/013：上传恢复只重建两道失败答案，不重放八道成功答案。"""

    import json

    from app.agents.submit.persist_personal import match_and_persist_personal_node
    from app.routers.upload_imports import _snapshot, _stage_counts
    from app.services.job_lifecycle import create_answer_generation_jobs

    _seed_user(test_db)
    import_id = "answer-retry-root"
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, status, current_attempt_no) "
        "VALUES (?, 1, 'answer-retry', 'hash', 'private', 'interview', "
        "'upload-pipeline-v1', 'partial_failed', 1)",
        (import_id,),
    )
    test_db.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES (?, 1, 'failed', 1)",
        (import_id,),
    )
    attempt_id = test_db.execute(
        "SELECT id FROM upload_attempts WHERE import_id = ?", (import_id,)
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO interview (id, url, company, round, owner_id, status, job_position) "
        "VALUES (901, 'https://test.com/retry', '测试公司', '一面', 1, 'approved', '后端')"
    )
    questions = [f"恢复用例题目 {index}" for index in range(1, 11)]
    for index, question in enumerate(questions, start=1):
        question_id = 1000 + index
        detail_id = 2000 + index
        test_db.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status, job_position) "
            "VALUES (?, ?, '系统设计', '恢复', 1, 'approved', '后端')",
            (question_id, question),
        )
        test_db.execute(
            "INSERT INTO questions_detail "
            "(id, interview_id, question, url, company, round, owner_id, status, "
            "job_position, import_id, source_ordinal) "
            "VALUES (?, 901, ?, 'https://test.com/retry', '测试公司', '一面', 1, "
            "'approved', '后端', ?, ?)",
            (detail_id, question, import_id, index),
        )
        test_db.execute(
            "INSERT INTO upload_stage_results "
            "(import_id, stage, unit_key, input_version, pipeline_version, status, error_code) "
            "VALUES (?, 'answer', ?, 1, 'upload-pipeline-v1', ?, ?)",
            (
                import_id,
                f"answer:{question_id}",
                "succeeded" if index <= 8 else "failed",
                None if index <= 8 else "UPSTREAM_TIMEOUT",
            ),
        )
    test_db.execute(
        "INSERT INTO upload_stage_results "
        "(import_id, stage, unit_key, input_version, pipeline_version, status, result_json) "
        "VALUES (?, 'extract', 'document', 1, 'upload-pipeline-v1', 'succeeded', ?)",
        (
            import_id,
            json.dumps({"提取计数": {"extracted": 10, "retained": 10, "excluded": 0}}),
        ),
    )
    test_db.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, "
        "upload_attempt_id, work_key) VALUES ('submit_import', 'completed', 1, ?, ?, 'extract')",
        (import_id, attempt_id),
    )
    parent_job_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    test_db.execute("UPDATE upload_imports SET interview_id=901, payload_json='{\"raw_text\":\"恢复原稿\"}' WHERE id=?", (import_id,))
    retry_job_id = test_db.execute(
        "INSERT INTO jobs(job_type,status,root_import_id,upload_attempt_id,lease_generation,locked_until) "
        "VALUES('submit_import','running',?,?,1,datetime('now','+120 seconds'))",
        (import_id, attempt_id),
    ).lastrowid
    test_db.commit()

    root = test_db.execute(
        "SELECT * FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    counts = _stage_counts(test_db, import_id)
    snapshot = _snapshot(root, counts=counts, conn=test_db)
    assert snapshot["status"] == "partial_failed"
    assert snapshot["counts"]["total"] == 10
    assert snapshot["counts"]["answered"] == 8
    assert snapshot["counts"]["failed"] == 2
    assert "retry_failed_steps" in snapshot["allowed_actions"]

    tagged_rows = [
        ["https://test.com/retry", "测试公司", "一面", question, "系统设计", "恢复", "", "L2-中等"]
        for question in questions
    ]
    outcomes = {
        "results": [
            {
                "new_id": index,
                "outcome": "matched",
                "canonical_id": 1000 + index + 1,
                "canonical_scope": "private",
            }
            for index in range(10)
        ]
    }
    with (
        patch("app.services.clustering.match_outcomes", AsyncMock(return_value=outcomes)),
        patch("app.db.connection.get_current_job_position", return_value="后端"),
        patch(
            "app.services.pipeline.queue._run_cluster_batch_in_background",
            AsyncMock(return_value=False),
        ),
    ):
        result = asyncio.run(
            match_and_persist_personal_node(
                {
                    "import_id": import_id,
                    "job_id": retry_job_id,
                    "_lease_generation": 1,
                    "_input_version": 1,
                    "user_id": 1,
                    "credential_scope": "user",
                    "job_position": "后端",
                    "saved_url": "https://test.com/retry",
                    "season": "",
                    "extracted_data": {
                        "公司": "测试公司",
                        "面试轮次": "一面",
                        "具体题目清单": questions,
                    },
                    "tagged_rows": tagged_rows,
                }
            )
        )

    assert result["answer_tasks"] == [
        (1009, "恢复用例题目 9"),
        (1010, "恢复用例题目 10"),
    ]
    new_jobs = create_answer_generation_jobs(
        test_db,
        parent_job_id,
        result["answer_tasks"],
        user_id=1,
        llm_scope="user",
        search_scope="user",
    )
    assert len(new_jobs) == 2
    retried_question_ids = {
        json.loads(row["payload"])["question_id"]
        for row in test_db.execute(
            "SELECT payload FROM job_payloads WHERE job_id IN (?, ?)",
            tuple(new_jobs),
        ).fetchall()
    }
    assert retried_question_ids == {1009, 1010}
    assert test_db.execute(
        "SELECT COUNT(*) FROM upload_stage_results WHERE import_id = ? "
        "AND stage = 'answer' AND status = 'pending'",
        (import_id,),
    ).fetchone()[0] == 2

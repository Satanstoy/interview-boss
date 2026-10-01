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
    enqueued: list[int] = []

    def _fake_enqueue(interview_id, *, owner_id=None, question_detail_ids=None, **kw):
        enqueued.extend(question_detail_ids or [])
        return 0

    with (
        patch("app.services.clustering.match_outcomes", AsyncMock(return_value=OUTCOMES)),
        patch("app.db.connection.get_current_job_position", return_value="后端开发"),
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

    # AC-006：failed 的题（new_id=0 → detail 601）不得入队列（阻断异步建新题）
    assert 601 not in enqueued, (
        "匹配失败（模型错误）的题目绝不能进入聚类队列异步建新题，AC-006"
    )
    assert 602 in enqueued, "no_match 真新题应正常入队聚类"
    assert result["match_failed"] == 1, "节点必须暴露 failed 计数供根状态聚合"


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

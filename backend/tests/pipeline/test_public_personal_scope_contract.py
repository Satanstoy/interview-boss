"""Regression tests for the public/personal contribution boundary."""

import asyncio
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated_app_db(app_db_isolation):
    """本文件会触达数据库连接，必须落在内存测试库（不能连生产库）。"""

    return app_db_isolation

def test_enqueue_questions_uses_interview_id_and_is_idempotent(test_db):
    # The workspace .env points at a proxy endpoint that resolves to the
    # RFC-2544 fake-IP range.  This test does not exercise outbound calls; keep
    # the import isolated from that environment-only startup check.
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.services.pipeline.queue import enqueue_questions

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'queue-owner', 'hash')"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status) VALUES (1, 'same://source', 7, 'approved')"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status) VALUES (2, 'same://source', NULL, 'approved')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, deleted_at) "
        "VALUES (11, 1, 'same://source', '个人题', NULL)"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, deleted_at) "
        "VALUES (22, 2, 'same://source', '公共题', NULL)"
    )
    test_db.commit()

    enqueue_questions(1, owner_id=7)
    enqueue_questions(1, owner_id=7)

    rows = test_db.execute(
        "SELECT interview_id, question_detail_id, owner_id "
        "FROM analysis_queue ORDER BY id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(1, 11, 7)]


def test_personal_cluster_writer_preserves_target_owner(test_db):
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.services.pipeline.writer import insert_new_clusters

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'personal-owner', 'hash')"
    )
    test_db.commit()

    cluster = {
        "representative": "如何设计一个幂等的任务队列？",
        "items": [
            {
                "question": "如何设计一个幂等的任务队列？",
                "cat1": "后端",
                "cat2": "系统设计",
                "tags": "幂等,队列",
                "diff_tag": "L2-中等",
                "url": "internal://personal",
                "company": "个人记录",
                "round": "一面",
            }
        ],
    }

    with patch(
        "app.services.embedding_service.encode_texts",
        return_value=np.zeros((1, 3), dtype=np.float32),
    ):
        ids = insert_new_clusters(
            test_db,
            [cluster],
            "后端开发",
            {},
            owner_id=7,
        )

    row = test_db.execute(
        "SELECT owner_id, status FROM question_bank WHERE id = ?", (ids[0],)
    ).fetchone()
    assert row["owner_id"] == 7
    assert row["status"] == "approved"


def test_personal_upload_does_not_queue_public_matches_or_sync_singletons(test_db):
    """个人上传只把真正的新题交给个人异步聚类流水线。"""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.agents.submit.persist_personal import match_and_persist_personal_node
        import app.services.clustering  # noqa: F401 - import under the safe test seam

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'submit-owner', 'hash')"
    )
    test_db.execute(
        "INSERT INTO question_bank (question, cat2, owner_id, status, job_position) "
        "VALUES ('公共代表题', '系统设计', NULL, 'approved', '后端开发')"
    )
    test_db.commit()

    tagged_rows = [
        [
            "internal://personal-batch",
            "个人公司",
            "一面",
            "已经存在公共库的题",
            "后端",
            "系统设计",
            "队列",
            "L2-中等",
        ],
        [
            "internal://personal-batch",
            "个人公司",
            "一面",
            "真正需要个人聚类的新题",
            "后端",
            "系统设计",
            "幂等",
            "L2-中等",
        ],
    ]

    calls = []

    async def _match(rows, existing, user_id=None):
        calls.append(rows)
        if len(calls) == 1:
            return {"matched": [], "unmatched": rows}
        return {
            "matched": [{"new_id": 0, "question_bank_id": 999}],
            "unmatched": [rows[1]],
        }

    async def _run_db(func):
        return func()

    state = {
        "extracted_data": {
            "公司": "个人公司",
            "面试轮次": "一面",
            "具体题目清单": ["已经存在公共库的题", "真正需要个人聚类的新题"],
        },
        "tagged_rows": tagged_rows,
        "saved_url": "internal://personal-batch",
        "season": "",
        "user_id": 7,
        "is_admin": False,
        "job_position": "后端开发",
    }

    with (
        patch("app.services.clustering.match_new_questions", new=AsyncMock(side_effect=_match)),
        patch("app.db.connection.get_current_job_position", return_value="后端开发"),
        patch("app.db.connection.run_db", new=_run_db),
        patch("app.services.pipeline.enqueue_questions") as mock_enqueue,
    ):
        result = asyncio.run(match_and_persist_personal_node(state))

    interview_id = result["saved_interview_id"]
    mock_enqueue.assert_called_once_with(
        interview_id,
        owner_id=7,
        question_detail_ids=[2],
    )
    assert test_db.execute(
        "SELECT COUNT(*) FROM question_bank WHERE owner_id = 7"
    ).fetchone()[0] == 0
    assert test_db.execute(
        "SELECT COUNT(*) FROM questions_detail WHERE interview_id = ?",
        (interview_id,),
    ).fetchone()[0] == 2


@pytest.mark.asyncio
async def test_cluster_llm_scope_follows_queue_owner_not_submitter(test_db):
    """公共聚类不能因提交者 ID 存在而切换到提交者的个人模型。"""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.services.pipeline import cluster_batch, dequeue_batch, enqueue_questions

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'scope-owner', 'hash')"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) "
        "VALUES (70, 'internal://personal-scope', 7, 'approved', '后端开发')"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) "
        "VALUES (71, 'internal://public-scope', NULL, 'approved', '后端开发')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, cat1, cat2, tags, diff_tag, job_position) "
        "VALUES (701, 70, 'internal://personal-scope', '个人题', '后端', '系统设计', '', 'L2', '后端开发')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, cat1, cat2, tags, diff_tag, job_position) "
        "VALUES (711, 71, 'internal://public-scope', '公共题', '后端', '系统设计', '', 'L2', '后端开发')"
    )
    test_db.commit()

    observed_user_ids = []

    async def _process(rows, existing, user_id=None):
        observed_user_ids.append(user_id)
        return {"matched_to_existing": [], "new_clusters": []}

    with (
        patch("app.services.pipeline.batch.process_incremental_batch", new=AsyncMock(side_effect=_process)),
        patch("app.services.pipeline.batch.get_index_manager"),
    ):
        enqueue_questions(71)
        public_batch = dequeue_batch(10)
        await cluster_batch(public_batch, user_id=999)
        test_db.execute("UPDATE analysis_queue SET status = 'done' WHERE interview_id = 71")
        test_db.commit()

        enqueue_questions(70, owner_id=7)
        personal_batch = dequeue_batch(10)
        await cluster_batch(personal_batch, user_id=999)

    assert observed_user_ids == [None, 7]


def test_source_cleanup_isolated_by_question_bank_owner(test_db):
    """同 URL 的个人来源清理不能删除公共题簇。"""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.db.operations import _cleanup_old_sources_txn_v2

    source_url = "https://same.example/interview"
    source_json = (
        '[{"url": "https://same.example/interview", "company": "同公司", "round": "一面"}]'
    )
    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'cleanup-owner', 'hash')"
    )
    test_db.execute(
        "INSERT INTO question_bank (id, question, sources, owner_id, job_position) "
        "VALUES (801, '公共簇', ?, NULL, '后端开发')",
        (source_json,),
    )
    test_db.execute(
        "INSERT INTO question_bank (id, question, sources, owner_id, job_position) "
        "VALUES (802, '个人簇', ?, 7, '后端开发')",
        (source_json,),
    )
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round) "
        "VALUES (801, ?, '同公司', '一面'), (802, ?, '同公司', '一面')",
        (source_url, source_url),
    )
    test_db.commit()

    test_db.execute("BEGIN")
    _cleanup_old_sources_txn_v2(
        test_db.cursor(), source_url, "后端开发", owner_id=7
    )
    test_db.commit()

    public_row = test_db.execute(
        "SELECT sources, deleted_at FROM question_bank WHERE id = 801"
    ).fetchone()
    personal_row = test_db.execute(
        "SELECT sources, deleted_at FROM question_bank WHERE id = 802"
    ).fetchone()
    assert public_row["deleted_at"] is None
    assert source_url in public_row["sources"]
    assert personal_row["deleted_at"] is not None


def test_normalized_source_reads_follow_question_bank_scope_not_url_owner(test_db):
    """同 URL 的个人/公共面经不能通过来源展示查询互相串库。"""
    from app.db.question_bank_sources import get_sources_filtered

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'source-owner', 'hash')"
    )
    source_url = "https://same.example/source"
    test_db.execute(
        "INSERT INTO question_bank (id, question, owner_id, status) VALUES "
        "(811, '公共题', NULL, 'approved'), (812, '个人题', 7, 'approved')"
    )
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round) VALUES "
        "(811, ?, '公共公司', '一面'), (812, ?, '个人公司', '一面')",
        (source_url, source_url),
    )
    test_db.commit()

    assert get_sources_filtered(test_db, 811, "public", 7)[0]["company"] == "公共公司"
    assert get_sources_filtered(test_db, 812, "public", 7) == []
    assert get_sources_filtered(test_db, 812, "mixed", 7)[0]["company"] == "个人公司"


def test_interview_delete_scopes_details_by_interview_id_for_same_url(test_db):
    """Deleting a private interview cannot soft-delete the public same-URL details."""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.routers.data import _delete_interview_txn

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) "
        "VALUES (7, 'delete-owner', 'hash')"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status) VALUES "
        "(7201, 'https://same.example/interview', 7, 'approved'), "
        "(7202, 'https://same.example/interview', NULL, 'approved')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, deleted_at) "
        "VALUES (7211, 7201, 'https://same.example/interview', '个人明细', NULL), "
        "(7212, 7202, 'https://same.example/interview', '公共明细', NULL)"
    )
    test_db.commit()

    test_db.execute("BEGIN")
    private_interview = test_db.execute(
        "SELECT id, url, owner_id FROM interview WHERE id = 7201"
    ).fetchone()
    _delete_interview_txn(test_db.cursor(), 7201, private_interview)
    test_db.commit()

    rows = test_db.execute(
        "SELECT interview_id, deleted_at FROM questions_detail "
        "WHERE id IN (7211, 7212) ORDER BY id"
    ).fetchall()
    assert rows[0]["deleted_at"] is not None
    assert rows[1]["deleted_at"] is None


def test_cluster_answer_jobs_follow_final_bank_scope(test_db):
    """Answer generation uses global config for public clusters and owner config for private clusters."""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.worker import _schedule_cluster_answer_jobs

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) VALUES "
        "(7, 'answer-owner', 'hash', 0), (1, 'answer-admin', 'hash', 1)"
    )
    test_db.execute(
        "INSERT INTO jobs (id, job_type, status, progress_total) "
        "VALUES (7001, 'cluster_batch', 'running', 1)"
    )
    test_db.execute(
        "INSERT INTO question_bank (id, question, owner_id, status, job_position) "
        "VALUES (7101, '公共新题', NULL, 'approved', '后端开发'), "
        "(7102, '个人新题', 7, 'approved', '后端开发')"
    )
    test_db.commit()

    public_jobs = asyncio.run(
        _schedule_cluster_answer_jobs(
            7001, [7101], owner_id=None, actor_id=1
        )
    )
    personal_jobs = asyncio.run(
        _schedule_cluster_answer_jobs(
            7001, [7102], owner_id=7, actor_id=1
        )
    )

    public_payload = test_db.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (public_jobs[0],)
    ).fetchone()[0]
    personal_payload = test_db.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (personal_jobs[0],)
    ).fetchone()[0]
    import json

    assert json.loads(public_payload)["llm_scope"] == "global"
    assert json.loads(public_payload)["search_scope"] == "public"
    assert json.loads(personal_payload)["llm_scope"] == "user"
    assert json.loads(personal_payload)["search_scope"] == "user"
    assert json.loads(personal_payload)["user_id"] == 7


def test_public_contribution_uses_snapshot_and_creates_separate_public_projection(test_db):
    """审核公共化不搬迁个人来源，且只把审核保留项送入公共队列。"""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.services.public_contributions import (
            approve_public_contribution,
            create_public_contribution_request,
            get_public_contribution_request,
            mark_public_contribution_queue_done,
        )

    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (7, 'contribution-owner', 'hash', 0)"
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (1, 'contribution-admin', 'hash', 1)"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (901, 'https://private.example/interview', '私有公司', '二面', '1. 原始题一\\n2. 原始题二', 7, 'approved', '后端开发')"
    )
    test_db.execute(
        "INSERT INTO questions_detail "
        "(id, interview_id, url, company, round, question, cat1, cat2, tags, diff_tag, job_position, status) "
        "VALUES (9011, 901, 'https://private.example/interview', '私有公司', '二面', '原始题一', '后端', '系统设计', '', 'L2', '后端开发', 'approved')"
    )
    test_db.execute(
        "INSERT INTO questions_detail "
        "(id, interview_id, url, company, round, question, cat1, cat2, tags, diff_tag, job_position, status) "
        "VALUES (9012, 901, 'https://private.example/interview', '私有公司', '二面', '原始题二', '后端', '系统设计', '', 'L2', '后端开发', 'approved')"
    )
    test_db.commit()

    request = create_public_contribution_request(test_db, "interview", 901, 7)
    request_id = request["id"]
    item_ids = [item["id"] for item in get_public_contribution_request(test_db, request_id)["items"]]

    test_db.execute(
        "UPDATE questions_detail SET question = '后来被用户修改的题' WHERE id = 9011"
    )
    test_db.commit()

    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        approved = approve_public_contribution(
            test_db,
            request_id,
            admin_id=1,
            excluded_item_ids=[item_ids[1]],
        )

    assert approved["status"] == "queued"
    assert test_db.execute(
        "SELECT owner_id FROM interview WHERE id = 901"
    ).fetchone()[0] == 7
    public_interview_id = approved["public_interview_id"]
    public_row = test_db.execute(
        "SELECT owner_id, status FROM interview WHERE id = ?",
        (public_interview_id,),
    ).fetchone()
    assert (public_row["owner_id"], public_row["status"]) == (None, "approved")
    public_question = test_db.execute(
        "SELECT question FROM questions_detail WHERE interview_id = ?",
        (public_interview_id,),
    ).fetchone()
    assert public_question["question"] == "原始题一"
    queue_row = test_db.execute(
        "SELECT id, owner_id, contribution_request_id, question_detail_id "
        "FROM analysis_queue WHERE contribution_request_id = ?",
        (request_id,),
    ).fetchone()
    assert (queue_row["owner_id"], queue_row["contribution_request_id"]) == (None, request_id)
    item_row = test_db.execute(
        "SELECT status, public_detail_id FROM public_contribution_items "
        "WHERE request_id = ? AND status = 'queued'",
        (request_id,),
    ).fetchone()
    assert item_row["public_detail_id"] == queue_row["question_detail_id"]

    test_db.execute(
        "UPDATE analysis_queue SET status = 'done' WHERE id = ?", (queue_row["id"],)
    )
    mark_public_contribution_queue_done(test_db, [queue_row["id"]])
    assert test_db.execute(
        "SELECT status FROM public_contribution_items WHERE request_id = ?",
        (request_id,),
    ).fetchone()[0] == "published"
    assert test_db.execute(
        "SELECT status FROM public_contribution_requests WHERE id = ?",
        (request_id,),
    ).fetchone()[0] == "partially_published"


def test_public_contribution_reuses_existing_public_detail_without_duplicate_queue(test_db):
    """重复公共化同一题时，第二个申请应直接闭环而不是卡在 queued。"""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.services.public_contributions import (
            approve_public_contribution,
            create_public_contribution_request,
        )

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'reuse-owner', 'hash')"
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) VALUES (1, 'reuse-admin', 'hash', 1)"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) VALUES "
        "(910, 'https://reuse.example/interview', NULL, 'approved', '后端开发'), "
        "(911, 'https://reuse.example/interview', 7, 'approved', '后端开发')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, deleted_at) VALUES "
        "(9101, 910, 'https://reuse.example/interview', '已存在公共题', NULL), "
        "(9111, 911, 'https://reuse.example/interview', '已存在公共题', NULL)"
    )
    test_db.commit()

    request = create_public_contribution_request(test_db, "interview", 911, 7)
    approved = approve_public_contribution(test_db, request["id"], 1)

    assert approved["status"] == "published"
    assert test_db.execute(
        "SELECT COUNT(*) FROM analysis_queue WHERE contribution_request_id = ?",
        (request["id"],),
    ).fetchone()[0] == 0


def test_public_contribution_cannot_be_rejected_after_queue_creation(test_db):
    """队列一旦创建，审核状态不能回退为 rejected。"""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.services.public_contributions import (
            approve_public_contribution,
            create_public_contribution_request,
            reject_public_contribution,
        )

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'reject-owner', 'hash')"
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) VALUES (1, 'reject-admin', 'hash', 1)"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status) VALUES "
        "(920, 'https://reject.example/interview', 7, 'approved')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, deleted_at) VALUES "
        "(9201, 920, 'https://reject.example/interview', '待处理题', NULL)"
    )
    test_db.commit()

    request = create_public_contribution_request(test_db, "interview", 920, 7)
    approved = approve_public_contribution(test_db, request["id"], 1)
    assert approved["status"] == "queued"
    with pytest.raises(ValueError):
        reject_public_contribution(test_db, request["id"], 1)


def test_public_contribution_failed_queue_can_close_after_retry(test_db):
    """队列重试成功后，failed 申请必须能最终变成 published。"""
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_: url,
    ):
        from app.services.public_contributions import (
            approve_public_contribution,
            create_public_contribution_request,
            mark_public_contribution_queue_done,
            mark_public_contribution_queue_failed,
        )

    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (7, 'retry-owner', 'hash')"
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) VALUES (1, 'retry-admin', 'hash', 1)"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status) VALUES "
        "(930, 'https://retry.example/interview', 7, 'approved')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, deleted_at) VALUES "
        "(9301, 930, 'https://retry.example/interview', '重试题', NULL)"
    )
    test_db.commit()

    request = create_public_contribution_request(test_db, "interview", 930, 7)
    approved = approve_public_contribution(test_db, request["id"], 1)
    queue_id = test_db.execute(
        "SELECT id FROM analysis_queue WHERE contribution_request_id = ?",
        (request["id"],),
    ).fetchone()[0]
    mark_public_contribution_queue_failed(test_db, [queue_id], "temporary")
    assert test_db.execute(
        "SELECT status FROM public_contribution_requests WHERE id = ?", (request["id"],)
    ).fetchone()[0] == "failed"

    test_db.execute("UPDATE analysis_queue SET status = 'done' WHERE id = ?", (queue_id,))
    mark_public_contribution_queue_done(test_db, [queue_id])
    assert test_db.execute(
        "SELECT status FROM public_contribution_requests WHERE id = ?", (request["id"],)
    ).fetchone()[0] == "published"

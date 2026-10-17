"""AC-015 / AC-016：失败子项恢复与清单投影一致性。

契约（contracts.md §3.3）：

- 每个 item 必须持有**当前有效**的 public resolution 才能 published；
  ``public_detail_id`` 存在不是成功证据；
- 只恢复失败子项：已成功的不重复处理，且不需要新增 INSERT 也能恢复；
- 申请在所有 item 发布前不得显示 published；
- 公共面经 ``questions_list`` 只包含 published 且未删除的明细，同 URL 追加
  新题时投影一致，失败题不得提前出现。
"""

from __future__ import annotations

import sqlite3
import json

import pytest

from app.db.migrations import run_migrations
from app.services.public_contributions import (
    mark_public_contribution_queue_done,
    publish_items_with_resolutions,
    refresh_public_interview_projection,
    request_publish_status,
)
from app.services.question_resolution import record_resolution


def test_queue_done_legacy_schema_does_not_leave_open_write_transaction():
    """A compatibility early return must close the transaction it opened."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE analysis_queue (id INTEGER PRIMARY KEY)")

    assert mark_public_contribution_queue_done(conn, [1]) == 0

    assert not conn.in_transaction
    conn.close()


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (1, 'https://src.example.com/1', 'S', '一面', '1.a', 101, 'approved', '后端')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (500, 'https://pub.example.com/1', 'P', '一面', '', NULL, 'approved', '后端')"
    )
    for detail_id, question in ((11, "TCP 三次握手"), (12, "TCP 四次挥手")):
        conn.execute(
            "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, job_position) "
            "VALUES (?, 1, ?, '网络', 'TCP', '后端')",
            (detail_id, question),
        )
    conn.execute(
        "INSERT INTO public_contribution_requests "
        "(id, source_type, source_id, requester_id, public_interview_id, status, snapshot_json, revision) "
        "VALUES (1, 'interview', 1, 101, 500, 'approved_for_processing', '{}', 1)"
    )
    for detail_id, question in ((511, "TCP 三次握手"), (512, "TCP 四次挥手")):
        conn.execute(
            "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, job_position) "
            "VALUES (?, 500, ?, '网络', 'TCP', '后端')",
            (detail_id, question),
        )
    # item 11：已成功 resolution；item 12：有 public_detail 但聚类失败
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, source_item_id, ordinal, status, snapshot_json, public_detail_id) "
        "VALUES (11, 1, 'question', 11, 1, 'processing', '{\"question\": \"TCP 三次握手\"}', 511)"
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, source_item_id, ordinal, status, snapshot_json, public_detail_id) "
        "VALUES (12, 1, 'question', 12, 2, 'processing', '{\"question\": \"TCP 四次挥手\"}', 512)"
    )
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status, frequency, sources, original_questions) "
        "VALUES (600, 'TCP 三次握手', '网络', 'TCP', NULL, 'approved', 1, '[]', '[]')"
    )
    conn.commit()
    return conn


def test_failed_item_blocks_publish_and_only_success_is_published():
    conn = _db()
    record_resolution(
        conn,
        detail_id=511,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    record_resolution(
        conn,
        detail_id=512,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=None,
        canonical_scope=None,
        status="failed",
        pipeline_version="v1",
        reason="UPSTREAM_TIMEOUT",
    )

    report = publish_items_with_resolutions(conn, request_id=1)
    assert report["published_item_ids"] == [11]
    assert report["pending_item_ids"] == [12]
    assert request_publish_status(conn, request_id=1) != "published"

    # 12 有 public_detail_id 也不能算成功
    item12 = conn.execute("SELECT status FROM public_contribution_items WHERE id = 12").fetchone()
    assert item12["status"] != "published"
    conn.close()


def test_terminal_item_failure_publishes_successful_siblings_and_projection():
    """A terminal failure must release the public interview publication gate."""
    conn = _db()
    from app.services.public_contributions import mark_public_contribution_queue_failed

    record_resolution(
        conn,
        detail_id=511,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'published' WHERE id = 11"
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'queued' WHERE id = 12"
    )
    conn.execute(
        "UPDATE interview SET publish_status = 'pending' WHERE id = 500"
    )
    queue_id = conn.execute(
        "INSERT INTO analysis_queue "
        "(interview_id, question_detail_id, status, owner_id, contribution_request_id) "
        "VALUES (500, 512, 'processing', NULL, 1) RETURNING id"
    ).fetchone()["id"]
    conn.commit()

    mark_public_contribution_queue_failed(conn, [queue_id], "temporary")

    request_status = conn.execute(
        "SELECT status FROM public_contribution_requests WHERE id = 1"
    ).fetchone()["status"]
    public_row = conn.execute(
        "SELECT publish_status, questions_list FROM interview WHERE id = 500"
    ).fetchone()
    assert request_status == "partially_published"
    assert public_row["publish_status"] == "published"
    assert public_row["questions_list"] == "1. TCP 三次握手"
    assert conn.execute(
        "SELECT status FROM public_contribution_items WHERE id = 12"
    ).fetchone()["status"] == "failed"
    conn.close()


def test_retry_restores_only_failed_item_without_new_inserts():
    conn = _db()
    record_resolution(
        conn,
        detail_id=511,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    record_resolution(
        conn,
        detail_id=512,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=None,
        canonical_scope=None,
        status="failed",
        pipeline_version="v1",
    )
    publish_items_with_resolutions(conn, request_id=1)
    details_before = conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0]

    # 恢复：只需为失败的 12 补上有效 resolution（复用既有 public_detail）
    record_resolution(
        conn,
        detail_id=512,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    report = publish_items_with_resolutions(conn, request_id=1)
    assert report["published_item_ids"] == [11, 12]
    assert report["reprocessed_item_ids"] == [12], "只恢复失败子项"
    assert request_publish_status(conn, request_id=1) == "published"
    assert conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == details_before
    conn.close()


def test_retry_requeues_only_failed_items_when_original_queue_row_is_done():
    """A done queue row with an invalid resolution must become executable again."""

    from app.services.public_contributions import retry_failed_public_items

    conn = _db()
    conn.execute(
        "UPDATE public_contribution_items SET status = 'published' WHERE id = 11"
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'failed' WHERE id = 12"
    )
    conn.execute(
        "INSERT INTO analysis_queue "
        "(interview_id, question_detail_id, status, owner_id, contribution_request_id) "
        "VALUES (500, 511, 'done', NULL, 1), (500, 512, 'done', NULL, 1)"
    )
    conn.commit()

    result = retry_failed_public_items(conn, request_id=1, admin_id=101)

    queue_statuses = {
        int(row["question_detail_id"]): row["status"]
        for row in conn.execute(
            "SELECT question_detail_id, status FROM analysis_queue ORDER BY question_detail_id"
        ).fetchall()
    }
    assert result["reprocessed_item_ids"] == [12]
    retry_payload = conn.execute(
        "SELECT p.payload FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.job_type = 'cluster_batch' AND j.root_import_id IS NULL "
        "ORDER BY j.id DESC LIMIT 1"
    ).fetchone()
    assert json.loads(retry_payload["payload"])["queue_scope"] == "public_contribution"
    assert queue_statuses == {511: "done", 512: "pending"}, queue_statuses
    assert conn.execute(
        "SELECT status FROM public_contribution_items WHERE id = 11"
    ).fetchone()["status"] == "published"
    conn.close()


def test_rootless_retry_reuses_active_legacy_cluster_job():
    """A retry must not race an active generic job that can consume public rows."""

    from app.services.public_contributions import retry_failed_public_items

    conn = _db()
    conn.execute(
        "UPDATE public_contribution_items SET status = 'published' WHERE id = 11"
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'failed' WHERE id = 12"
    )
    conn.execute(
        "INSERT INTO analysis_queue "
        "(interview_id, question_detail_id, status, owner_id, contribution_request_id) "
        "VALUES (500, 511, 'done', NULL, 1), (500, 512, 'done', NULL, 1)"
    )
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, idempotency_key) "
        "VALUES ('cluster_batch', 'running', 101, 'legacy-rootless-active')"
    )
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, '{\"user_id\":101}')",
        (int(cursor.lastrowid),),
    )
    conn.commit()

    result = retry_failed_public_items(conn, request_id=1, admin_id=101)

    assert result["reprocessed_item_ids"] == [12]
    assert conn.execute(
        "SELECT status FROM analysis_queue WHERE question_detail_id = 512"
    ).fetchone()["status"] == "pending"
    assert conn.execute(
        "SELECT status FROM public_contribution_items WHERE id = 12"
    ).fetchone()["status"] == "queued"
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL AND status IN ('pending', 'queued', 'running')"
    ).fetchone()[0] == 1
    conn.close()


def test_root_bound_public_retry_preflights_global_before_cluster_dispatch():
    """An approved public retry must re-probe system credentials on the same root."""

    from app.services.job_lifecycle import CLUSTER_BATCH_JOB_TYPE, claim_dispatch_batch
    from app.services.public_contributions import retry_failed_public_items
    from app.services.credential_preflight import run_credential_preflight

    conn = _db()
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, "
        "status, contribution_request_id) "
        "VALUES ('public-root', 101, 'share-retry', 'hash', 'share', 'interview', 'v1', "
        "'{\"credential_scope\":\"user\",\"post_approval_credential_scope\":\"global\"}', '{}', "
        "'needs_action', 1)"
    )
    attempt_id = conn.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES ('public-root', 1, 'active', 101)"
    ).lastrowid
    conn.execute(
        "UPDATE public_contribution_items SET status = 'failed' WHERE id = 12"
    )
    conn.execute(
        "INSERT INTO analysis_queue "
        "(interview_id, question_detail_id, status, owner_id, contribution_request_id, root_import_id) "
        "VALUES (500, 511, 'done', NULL, 1, 'public-root'), "
        "(500, 512, 'done', NULL, 1, 'public-root')"
    )
    conn.commit()

    retried = retry_failed_public_items(conn, request_id=1, admin_id=101)
    assert retried["reprocessed_item_ids"] == [12]
    preflight = conn.execute(
        "SELECT j.id, j.upload_attempt_id, p.payload FROM jobs j "
        "JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = 'public-root' AND j.job_type = 'credential_preflight'"
    ).fetchone()
    assert preflight is not None
    assert preflight["upload_attempt_id"] == attempt_id
    assert '"credential_scope": "global"' in preflight["payload"]

    # The cluster work stays in the outbox until the global probe succeeds.
    assert claim_dispatch_batch(conn, job_type=CLUSTER_BATCH_JOB_TYPE) == []
    outcome = run_credential_preflight(
        conn,
        job_id=preflight["id"],
        probe=lambda _credential: {"status": "ok", "latency_ms": 2},
        global_config_loader=lambda: {
            "api_key": "system-key",
            "base_url": "https://system.example/v1",
            "model": "system-model",
        },
    )
    conn.commit()
    assert outcome.status == "ok"
    dispatchable = claim_dispatch_batch(conn, job_type=CLUSTER_BATCH_JOB_TYPE)
    assert len(dispatchable) == 1
    assert dispatchable[0]["job_type"] == CLUSTER_BATCH_JOB_TYPE
    conn.close()


def test_questions_list_only_contains_published_items():
    conn = _db()
    record_resolution(
        conn,
        detail_id=511,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    publish_items_with_resolutions(conn, request_id=1)
    refresh_public_interview_projection(conn, public_interview_id=500)
    row = conn.execute("SELECT questions_list FROM interview WHERE id = 500").fetchone()
    assert "TCP 三次握手" in row["questions_list"]
    assert "TCP 四次挥手" not in row["questions_list"], "失败题不得提前出现在清单"

    record_resolution(
        conn,
        detail_id=512,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    publish_items_with_resolutions(conn, request_id=1)
    refresh_public_interview_projection(conn, public_interview_id=500)
    row = conn.execute("SELECT questions_list FROM interview WHERE id = 500").fetchone()
    assert "TCP 三次握手" in row["questions_list"]
    assert "TCP 四次挥手" in row["questions_list"], "同 URL 追加的题发布后必须出现且仅一次"
    assert row["questions_list"].count("TCP 三次握手") == 1
    conn.close()


def test_deleted_item_is_excluded_from_projection():
    conn = _db()
    for detail_id in (511, 512):
        record_resolution(
            conn,
            detail_id=detail_id,
            occurrence_scope="public",
            occurrence_owner_id=None,
            canonical_id=600,
            canonical_scope="public",
            status="matched",
            pipeline_version="v1",
        )
    publish_items_with_resolutions(conn, request_id=1)
    conn.execute("UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP WHERE id = 512")
    conn.commit()
    refresh_public_interview_projection(conn, public_interview_id=500)
    row = conn.execute("SELECT questions_list FROM interview WHERE id = 500").fetchone()
    assert "TCP 三次握手" in row["questions_list"]
    assert "TCP 四次挥手" not in row["questions_list"]
    conn.close()


def test_invalidated_resolution_blocks_publish():
    conn = _db()
    record_resolution(
        conn,
        detail_id=511,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    # resolution 被失效（公共题重聚类）→ 不得 published
    conn.execute(
        "UPDATE question_resolutions SET invalidated_at = CURRENT_TIMESTAMP WHERE detail_id = 511"
    )
    conn.commit()
    report = publish_items_with_resolutions(conn, request_id=1)
    assert report["published_item_ids"] == []
    assert request_publish_status(conn, request_id=1) != "published"
    conn.close()


# ── AC-016 / contracts §3.3：同 URL 追加不得破坏既有公开投影 ──────────────


def _projection(question: str) -> dict:
    return {
        "source": {
            "source_url": "https://pub.example.com/1",
            "season": "2026春招",
            "job_position": "后端",
        },
        "items": [
            {
                "question": question,
                "cat1": "数据库",
                "cat2": "Redis",
                "difficulty": "中等",
            }
        ],
    }


def _seed_second_request(conn, *, detail_id: int, question: str) -> None:
    """同一 URL 的第二次贡献：request 2 + 一条 queued 子项 + 对应公共明细。"""

    # 同 URL 的追加来自另一份私有面经（source_id 不同），
    # UNIQUE(source_type, source_id, requester_id) 不允许同源重复申请
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, "
        "status, job_position) "
        "VALUES (2, 'https://pub.example.com/1', 'S2', '二面', '1.b', 101, 'approved', '后端')"
    )
    conn.execute(
        "INSERT INTO public_contribution_requests "
        "(id, source_type, source_id, requester_id, public_interview_id, status, "
        "snapshot_json, revision) "
        "VALUES (2, 'interview', 2, 101, 500, 'approved_for_processing', '{}', 1)"
    )
    # 先建公共明细，再建引用它的 item（FK：items.public_detail_id → questions_detail.id）
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, job_position) "
        "VALUES (?, 500, ?, '数据库', 'Redis', '后端')",
        (detail_id, question),
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, source_item_id, ordinal, status, "
        "snapshot_json, public_detail_id) "
        "VALUES (21, 2, 'question', 12, 1, 'queued', '{}', ?)",
        (detail_id,),
    )
    conn.commit()


def _seed_published_baseline(conn) -> None:
    """让 request 1 的 item 11 成为「已发布」：清单必须由它重建而来。"""

    record_resolution(
        conn,
        detail_id=511,
        occurrence_scope="public",
        occurrence_owner_id=None,
        canonical_id=600,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    conn.execute("UPDATE public_contribution_items SET status = 'published' WHERE id = 11")
    conn.execute("UPDATE interview SET questions_list = '1. TCP 三次握手' WHERE id = 500")
    conn.commit()


def test_same_url_reuse_keeps_previously_published_questions():
    """同 URL 追加贡献时，公共面经清单不得丢掉已发布的既有题目。"""

    from app.services.public_contributions import (
        materialize_public_interview_from_projection,
    )

    conn = _db()
    _seed_published_baseline(conn)
    _seed_second_request(conn, detail_id=521, question="Redis 持久化")

    materialize_public_interview_from_projection(
        conn,
        _projection("Redis 持久化"),
        source_id=1,
        requester_id=101,
        job_position="后端",
    )
    conn.commit()

    questions_list = conn.execute(
        "SELECT questions_list FROM interview WHERE id = 500"
    ).fetchone()["questions_list"]
    assert "TCP 三次握手" in questions_list, (
        "同 URL 复用分支用本次投影覆盖了清单，已发布的既有题目被丢弃（AC-016）"
    )
    conn.close()


def test_same_url_reuse_does_not_expose_unpublished_questions():
    """清单只能包含已发布明细：本次追加的子项仍是 queued，不得提前出现。"""

    from app.services.public_contributions import (
        materialize_public_interview_from_projection,
    )

    conn = _db()
    _seed_published_baseline(conn)
    _seed_second_request(conn, detail_id=521, question="Redis 持久化")

    materialize_public_interview_from_projection(
        conn,
        _projection("Redis 持久化"),
        source_id=1,
        requester_id=101,
        job_position="后端",
    )
    conn.commit()

    questions_list = conn.execute(
        "SELECT questions_list FROM interview WHERE id = 500"
    ).fetchone()["questions_list"]
    assert "TCP 三次握手" in questions_list, "已发布题目必须仍在清单里"
    assert "Redis 持久化" not in questions_list, (
        "尚未 published 的子项不得出现在公开清单里（contracts §3.3）"
    )
    conn.close()


def test_failed_request_cannot_be_reapproved():
    """contracts §3.2：failed 技术状态不得重新 approve，只能走公共 retry 入口。"""

    from app.models.upload_contracts import build_review_projection_request
    from app.services.public_contributions import (
        StateConflict,
        approve_public_contribution_v2,
    )

    conn = _db()
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'failed' WHERE id = 1"
    )
    conn.commit()
    details_before = conn.execute(
        "SELECT COUNT(*) FROM questions_detail WHERE interview_id = 500"
    ).fetchone()[0]

    review_request = build_review_projection_request(
        {"expected_revision": 1, "excluded_item_ids": [], "review_fields": {}},
        source_type="interview",
    )
    with pytest.raises(StateConflict):
        approve_public_contribution_v2(
            conn, request_id=1, admin_id=101, review_request=review_request
        )
    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) FROM questions_detail WHERE interview_id = 500"
    ).fetchone()[0] == details_before, "被拒的 approve 不得重复物化明细"
    conn.close()

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

from app.db.migrations import run_migrations
from app.services.public_contributions import (
    publish_items_with_resolutions,
    refresh_public_interview_projection,
    request_publish_status,
)
from app.services.question_resolution import record_resolution


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
        "(id, source_type, source_id, requester_id, status, snapshot_json, revision) "
        "VALUES (1, 'interview', 1, 101, 'approved_for_processing', '{}', 1)"
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

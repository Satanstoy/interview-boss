"""AC-007 / UR-007：残余队列必须被推进（reconciler + 轮转）。

契约（contracts.md §2.5）：

- 每 60 秒对账：给“有 pending 但无活跃 job”的合法桶补一个幂等 job；
- 一批完成后持久化下一批工作，不指望下一次上传来推进；
- 选桶按最早可用时间轮转，不能永远选公共大桶（私人桶必须在有限轮次被执行）；
- 孤儿/被删原文转可解释 blocked，不空转、不删除证据。
"""

from __future__ import annotations

import sqlite3

from app.db.migrations import run_migrations
from app.services.upload_queue import (
    collect_pending_buckets,
    ensure_bucket_job,
    reconcile_pending_buckets,
    select_next_bucket,
)


def _db(tmp_path=None):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    for uid in (101, 102):
        conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (1, 'https://a.example.com/1', 'A', '一面', '1.x', 101, 'approved', '后端')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (2, 'https://a.example.com/2', 'B', '一面', '1.y', NULL, 'approved', '后端')"
    )
    for i in range(7):
        conn.execute(
            "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
            "target_intent, source_type, pipeline_version) "
            "VALUES (?, 101, ?, 'h', 'private', 'interview', 'v1')",
            (f"imp-p{i}", f"k-p{i}"),
        )
        conn.execute(
            "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2) "
            "VALUES (?, 1, ?, 'a', 'b')",
            (1000 + i, f"私有题 {i}"),
        )
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, question_detail_id, owner_id, status, root_import_id) "
            "VALUES (1, ?, 101, 'pending', ?)",
            (1000 + i, f"imp-p{i}"),
        )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-public', 101, 'k-pub', 'h', 'share', 'interview', 'v1')"
    )
    for i in range(11):
        conn.execute(
            "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2) "
            "VALUES (?, 2, ?, 'a', 'b')",
            (2000 + i, f"公共题 {i}"),
        )
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, question_detail_id, owner_id, status, root_import_id) "
            "VALUES (2, ?, NULL, 'pending', 'imp-public')",
            (2000 + i,),
        )
    conn.commit()
    return conn


def test_every_legal_bucket_gets_a_job(tmp_path):
    conn = _db(tmp_path)
    buckets = collect_pending_buckets(conn)
    assert len(buckets) >= 8, "7 个私人桶 + 1 个公共桶"
    report = reconcile_pending_buckets(conn)
    assert report["jobs_created"] == len(buckets)
    # 每个桶恰好一个活跃 job
    for bucket in buckets:
        active = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? AND work_key = ? "
            "AND status IN ('pending','queued','running')",
            (bucket["root_import_id"], bucket["work_key"]),
        ).fetchone()[0]
        assert active == 1
    conn.close()


def test_reconcile_is_idempotent(tmp_path):
    conn = _db(tmp_path)
    first = reconcile_pending_buckets(conn)
    second = reconcile_pending_buckets(conn)
    assert first["jobs_created"] > 0
    assert second["jobs_created"] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == first["jobs_created"]
    conn.close()


def test_bucket_with_active_job_is_skipped(tmp_path):
    conn = _db(tmp_path)
    bucket = collect_pending_buckets(conn)[0]
    ensure_bucket_job(conn, bucket=bucket, created_by=101)
    report = reconcile_pending_buckets(conn)
    assert report["jobs_created"] == report["buckets"] - 1
    conn.close()


def test_earliest_available_rotation_prevents_starvation(tmp_path):
    """连续公共流量下，私人桶必须在有限轮次内被选中。"""

    conn = _db(tmp_path)
    selected_counts = {}
    recently_selected: list[str] = []
    for _ in range(12):
        buckets = collect_pending_buckets(conn)
        chosen = select_next_bucket(buckets, recently_selected=recently_selected)
        assert chosen is not None
        key = chosen["scope_key"]
        selected_counts[key] = selected_counts.get(key, 0) + 1
        recently_selected.append(key)
    assert any(":user:101" in k for k in selected_counts), "私人桶不得被饿死"
    assert any("public" in k for k in selected_counts)
    conn.close()


def test_orphan_rows_become_blocked_not_spinning(tmp_path):
    conn = _db(tmp_path)
    # 孤儿：明细所属面经被软删
    conn.execute("UPDATE interview SET deleted_at = CURRENT_TIMESTAMP WHERE id = 1")
    conn.commit()
    report = reconcile_pending_buckets(conn)
    assert report["orphans_blocked"] >= 7
    remaining = conn.execute(
        "SELECT COUNT(*) FROM analysis_queue WHERE status = 'pending' AND interview_id = 1"
    ).fetchone()[0]
    assert remaining == 0, "被删原文的队列行不得继续空转"
    # 证据保留
    assert (
        conn.execute("SELECT COUNT(*) FROM analysis_queue WHERE interview_id = 1").fetchone()[0]
        >= 7
    )
    conn.close()


def test_failed_public_contribution_item_is_not_reconciled_until_explicit_retry():
    conn = _db()
    conn.execute(
        "INSERT INTO public_contribution_requests "
        "(id, source_type, source_id, requester_id, public_interview_id, status, snapshot_json, revision) "
        "VALUES (99, 'interview', 1, 101, 2, 'partially_published', '{}', 1)"
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, source_item_id, ordinal, status, snapshot_json, public_detail_id) "
        "VALUES (9900, 99, 'question', 2000, 1, 'failed', '{}', 2000), "
        "       (9901, 99, 'question', 2001, 2, 'queued', '{}', 2001)"
    )
    conn.execute(
        "UPDATE analysis_queue SET contribution_request_id = 99 "
        "WHERE question_detail_id IN (2000, 2001)"
    )
    conn.commit()

    public_bucket = next(
        bucket for bucket in collect_pending_buckets(conn)
        if bucket["root_import_id"] == "imp-public"
    )
    assert public_bucket["pending_count"] == 10

    # The explicit retry transition changes the failed item back to queued,
    # which makes that same durable queue row eligible again.
    conn.execute(
        "UPDATE public_contribution_items SET status = 'queued' WHERE id = 9900"
    )
    conn.commit()
    public_bucket = next(
        bucket for bucket in collect_pending_buckets(conn)
        if bucket["root_import_id"] == "imp-public"
    )
    assert public_bucket["pending_count"] == 11
    conn.close()

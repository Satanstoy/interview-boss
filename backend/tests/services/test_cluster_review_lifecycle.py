"""Tests for the durable, version-aware cluster review state machine."""

import json

import pytest
from fastapi import HTTPException


def _seed_clusters(conn):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, job_position, frequency, status, owner_id, "
        "original_questions) VALUES (1, ?, 'B', 'B1', '后端开发', 2, 'approved', NULL, ?)",
        ("介绍 RAG 流程", json.dumps(["RAG 是怎么做的", "介绍 RAG 流程"], ensure_ascii=False)),
    )
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, job_position, frequency, status, owner_id, "
        "original_questions) VALUES (2, '独立题', 'B', 'B1', '后端开发', 1, 'approved', NULL, '[]')"
    )
    conn.commit()


def test_cluster_version_is_order_insensitive(test_db):
    from app.services.cluster_review_lifecycle import cluster_version_from_row

    _seed_clusters(test_db)
    row = test_db.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
    first = cluster_version_from_row(row)
    test_db.execute(
        "UPDATE question_bank SET original_questions = ? WHERE id = 1",
        (json.dumps(["介绍 RAG 流程", "RAG 是怎么做的", "RAG 是怎么做的"], ensure_ascii=False),),
    )
    row = test_db.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
    assert cluster_version_from_row(row) == first


def test_mark_is_idempotent_and_new_version_gets_one_new_task(test_db):
    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

    _seed_clusters(test_db)
    first = mark_cluster_review_pending(test_db, 1, "new_cluster")
    test_db.commit()
    second = mark_cluster_review_pending(test_db, 1, "new_variant_matched")
    test_db.commit()

    assert first["task_id"] == second["task_id"]
    assert test_db.execute(
        "SELECT COUNT(*) FROM cluster_review_tasks WHERE cluster_id = 1"
    ).fetchone()[0] == 1

    test_db.execute(
        "UPDATE question_bank SET original_questions = ? WHERE id = 1",
        (json.dumps(["RAG 是怎么做的", "介绍 RAG 流程", "RAG 如何落地"], ensure_ascii=False),),
    )
    third = mark_cluster_review_pending(test_db, 1, "new_variant_matched")
    test_db.commit()
    assert third["task_id"] != first["task_id"]
    assert test_db.execute(
        "SELECT COUNT(*) FROM cluster_review_tasks WHERE cluster_id = 1"
    ).fetchone()[0] == 2


def test_backfill_dry_run_and_pending_preservation(test_db):
    from app.services.cluster_review_lifecycle import backfill_cluster_review_state

    _seed_clusters(test_db)
    test_db.execute(
        "INSERT INTO quality_issue "
        "(qb_id, issue_type, suggested_action, reason, confidence, status, created_at) "
        "VALUES (1, 'weak_representative', 'refine_representative', 'legacy', 0.7, 'pending', datetime('now'))"
    )
    test_db.commit()

    dry = backfill_cluster_review_state(test_db, dry_run=True)
    assert dry["active_clusters"] == 2
    assert test_db.execute("SELECT COUNT(*) FROM cluster_review_state").fetchone()[0] == 0
    assert test_db.execute("SELECT COUNT(*) FROM cluster_review_tasks").fetchone()[0] == 0

    report = backfill_cluster_review_state(test_db, dry_run=False)
    test_db.commit()
    assert report["pending_preserved"] == 1
    assert test_db.execute(
        "SELECT status FROM cluster_review_state WHERE cluster_id = 1"
    ).fetchone()[0] == "needs_human"
    assert test_db.execute(
        "SELECT COUNT(*) FROM cluster_review_tasks WHERE cluster_id = 1"
    ).fetchone()[0] == 0
    assert test_db.execute(
        "SELECT COUNT(*) FROM cluster_review_tasks WHERE cluster_id = 2"
    ).fetchone()[0] == 1

    again = backfill_cluster_review_state(test_db, dry_run=False)
    test_db.commit()
    assert again["tasks_created"] == 0
    assert test_db.execute("SELECT COUNT(*) FROM cluster_review_tasks").fetchone()[0] == 1


def test_dispatch_claim_and_finish_updates_state(test_db):
    from app.services.cluster_review_lifecycle import (
        claim_review_dispatch_batch,
        claim_review_task,
        finish_review_task,
        mark_cluster_review_pending,
        mark_review_task_dispatched,
    )

    _seed_clusters(test_db)
    marked = mark_cluster_review_pending(test_db, 2, "migration_backfill")
    test_db.commit()
    batch = claim_review_dispatch_batch(test_db, limit=10)
    assert len(batch) == 1
    assert batch[0]["id"] == marked["task_id"]
    mark_review_task_dispatched(test_db, marked["task_id"], "arq-1")
    task = claim_review_task(test_db, marked["task_id"])
    assert task["status"] == "running"
    result = finish_review_task(test_db, task)
    test_db.commit()

    assert result["status"] == "passed"
    assert test_db.execute(
        "SELECT status, reviewed_version FROM cluster_review_state WHERE cluster_id = 2"
    ).fetchone()[0] == "passed"
    assert test_db.execute(
        "SELECT status FROM cluster_review_tasks WHERE id = ?", (marked["task_id"],)
    ).fetchone()[0] == "completed"


def test_versioned_approval_rejects_stale_issue(test_db):
    from app.services.quality_issue_ops import approve_issue

    _seed_clusters(test_db)
    test_db.execute(
        "INSERT INTO quality_issue "
        "(qb_id, issue_type, suggested_action, reason, suggested_value, confidence, status, "
        "created_at, review_version, variant_key) VALUES "
        "(1, 'weak_representative', 'refine_representative', 'stale', '新代表题', 0.9, 'pending', "
        "datetime('now'), 'stale-version', '')"
    )
    test_db.commit()

    with pytest.raises(HTTPException) as exc:
        approve_issue(test_db, admin_id=1, issue_id=1)
    assert exc.value.status_code == 409
    assert test_db.execute("SELECT question FROM question_bank WHERE id = 1").fetchone()[0] == "介绍 RAG 流程"


def test_approve_rolls_back_partial_cluster_mutation(test_db, monkeypatch):
    """审批执行失败时，题库和 quality_issue 都回滚，不污染线程连接。"""
    from app.services.quality_issue_ops import approve_issue

    _seed_clusters(test_db)
    test_db.execute(
        "INSERT INTO quality_issue "
        "(qb_id, issue_type, suggested_action, reason, suggested_value, confidence, status, created_at) "
        "VALUES (1, 'weak_representative', 'refine_representative', '失败演练', '新代表题', 0.9, 'pending', datetime('now'))"
    )
    test_db.commit()

    def fail_after_mutation(conn, issue, operator_id=None):
        conn.execute(
            "UPDATE question_bank SET question = '不应持久化的中间值' WHERE id = 1"
        )
        raise RuntimeError("模拟审批失败")

    monkeypatch.setattr(
        "app.services.quality_issue_ops.execute_issue", fail_after_mutation
    )

    with pytest.raises(RuntimeError, match="模拟审批失败"):
        approve_issue(test_db, admin_id=1, issue_id=1)

    assert test_db.execute(
        "SELECT question FROM question_bank WHERE id = 1"
    ).fetchone()[0] == "介绍 RAG 流程"
    assert test_db.execute(
        "SELECT status FROM quality_issue WHERE id = 1"
    ).fetchone()[0] == "pending"


def test_manual_scan_state_tracks_versioned_pending_issue(test_db):
    """通用扫描完成后，状态表按当前版本反映是否需要人工处理。"""
    from app.services.cluster_review_lifecycle import (
        cluster_version_from_row,
        sync_review_state_after_scan,
    )

    _seed_clusters(test_db)
    test_db.execute(
        "INSERT INTO quality_issue "
        "(qb_id, issue_type, suggested_action, reason, confidence, status, created_at) "
        "VALUES (1, 'mismerge', 'split', '需要人工确认', 0.9, 'pending', datetime('now'))"
    )
    test_db.commit()

    result = sync_review_state_after_scan(test_db, [1, 2])
    test_db.commit()

    assert result == {"clusters": 2, "passed": 1, "needs_human": 1}
    state = test_db.execute(
        "SELECT current_version, reviewed_version, status FROM cluster_review_state WHERE cluster_id = 1"
    ).fetchone()
    current = cluster_version_from_row(
        test_db.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
    )
    assert state[0] == current
    assert state[1] is None
    assert state[2] == "needs_human"

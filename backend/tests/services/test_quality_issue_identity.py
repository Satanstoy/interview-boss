"""Stable quality-review identity and legacy data migration tests."""

import json


def _seed_question(conn):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, frequency, status, cat1, cat2, original_questions) "
        "VALUES (1, '介绍 RAG 流程', 3, 'approved', 'B', 'B1', ?)",
        (json.dumps(["介绍 RAG 流程", "研究生阶段研究方向是什么"], ensure_ascii=False),),
    )
    conn.commit()


def _issue_values(fingerprint, version, *, status="pending"):
    return {
        "qb_id": 1,
        "variant_index": 1,
        "issue_type": "mismerge",
        "suggested_action": "split",
        "reason": "考察点不同",
        "suggested_value": "你研究生阶段的研究方向是什么？",
        "confidence": 0.92,
        "status": status,
        "target_qb_id": None,
        "new_cat2": None,
        "source_question": "研究生阶段研究方向是什么",
        "source_cat2": "B1",
        "review_version": version,
        "review_task_id": f"task-{version}",
        "trigger_reason": "test",
        "variant_key": "1",
        "issue_fingerprint": fingerprint,
    }


def test_same_finding_reuses_one_row_across_review_versions(test_db):
    from app.db.quality_issue_identity import build_issue_fingerprint, upsert_quality_issue

    _seed_question(test_db)
    fingerprint = build_issue_fingerprint("mismerge", "研究生阶段研究方向是什么")

    first_id, first_created = upsert_quality_issue(
        test_db, _issue_values(fingerprint, "version-1")
    )
    test_db.commit()
    second_id, second_created = upsert_quality_issue(
        test_db, _issue_values(fingerprint, "version-2")
    )
    test_db.commit()

    assert first_created is True
    assert second_created is False
    assert first_id == second_id
    assert test_db.execute(
        "SELECT COUNT(*) FROM quality_issue WHERE issue_fingerprint = ?",
        (fingerprint,),
    ).fetchone()[0] == 1
    row = test_db.execute(
        "SELECT status, review_version FROM quality_issue WHERE id = ?", (first_id,)
    ).fetchone()
    assert tuple(row) == ("pending", "version-2")


def test_resolved_finding_is_not_reopened_by_a_later_scan(test_db):
    from app.db.quality_issue_identity import build_issue_fingerprint, upsert_quality_issue

    _seed_question(test_db)
    fingerprint = build_issue_fingerprint("mismerge", "研究生阶段研究方向是什么")
    issue_id, _ = upsert_quality_issue(
        test_db, _issue_values(fingerprint, "version-1")
    )
    test_db.execute(
        "UPDATE quality_issue SET status = 'done', reviewed_at = datetime('now') WHERE id = ?",
        (issue_id,),
    )
    test_db.commit()

    reused_id, created = upsert_quality_issue(
        test_db, _issue_values(fingerprint, "version-2")
    )
    test_db.commit()

    assert (reused_id, created) == (issue_id, False)
    assert test_db.execute(
        "SELECT status, review_version FROM quality_issue WHERE id = ?", (issue_id,)
    ).fetchone()[0] == "done"
    assert test_db.execute("SELECT COUNT(*) FROM quality_issue").fetchone()[0] == 1


def test_approved_old_snapshot_is_reopened_in_the_same_row(test_db):
    from app.db.quality_issue_identity import build_issue_fingerprint, upsert_quality_issue

    _seed_question(test_db)
    fingerprint = build_issue_fingerprint("mismerge", "研究生阶段研究方向是什么")
    issue_id, _ = upsert_quality_issue(
        test_db, _issue_values(fingerprint, "version-1")
    )
    test_db.execute(
        "UPDATE quality_issue SET status = 'approved' WHERE id = ?", (issue_id,)
    )
    test_db.commit()

    reused_id, reopened = upsert_quality_issue(
        test_db, _issue_values(fingerprint, "version-2")
    )
    test_db.commit()

    assert (reused_id, reopened) == (issue_id, True)
    assert test_db.execute(
        "SELECT status, review_version FROM quality_issue WHERE id = ?", (issue_id,)
    ).fetchone()[0:] == ("pending", "version-2")


def test_quality_issue_migration_backfills_legacy_fingerprint(test_db):
    from app.db.migrations.clustering import _migration_077_quality_issue_identity
    from app.db.quality_issue_identity import build_issue_fingerprint

    _seed_question(test_db)
    test_db.execute(
        "INSERT INTO quality_issue "
        "(qb_id, variant_index, issue_type, suggested_action, reason, confidence, status, created_at) "
        "VALUES (1, 1, 'mismerge', 'split', '历史数据', 0.9, 'pending', datetime('now'))"
    )
    test_db.commit()

    _migration_077_quality_issue_identity(test_db)
    test_db.commit()

    row = test_db.execute(
        "SELECT issue_fingerprint, status FROM quality_issue WHERE qb_id = 1"
    ).fetchone()
    assert row[0] == build_issue_fingerprint("mismerge", "研究生阶段研究方向是什么")
    assert row[1] == "pending"

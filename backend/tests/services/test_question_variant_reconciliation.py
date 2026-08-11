"""跨题簇原始题目归属修复与写入防护测试。"""

import json

import pytest


def _insert_qb(
    conn,
    qb_id,
    question,
    originals,
    *,
    cat1="A",
    cat2="A1",
    sources=None,
    original_sources=None,
):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, status, owner_id, sources, "
        "original_questions, original_question_sources, cluster_id) "
        "VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, ?, ?, ?)",
        (
            qb_id,
            question,
            cat1,
            cat2,
            max(1, len(originals)),
            json.dumps(sources or [], ensure_ascii=False),
            json.dumps(originals, ensure_ascii=False),
            json.dumps(
                original_sources
                or [
                    {
                        "question": original,
                        "sources": [],
                    }
                    for original in originals
                ],
                ensure_ascii=False,
            ),
            qb_id,
        ),
    )


def test_scan_groups_same_normalized_original_across_clusters(test_db):
    from app.services.question_variant_reconciliation import (
        scan_cross_cluster_variant_groups,
    )

    _insert_qb(test_db, 1, "题簇一", ["关于研究生方向？"])
    _insert_qb(test_db, 2, "题簇二", ["关于研究生方向"])
    _insert_qb(test_db, 3, "独立题", ["只出现一次"])
    test_db.commit()

    groups = scan_cross_cluster_variant_groups(test_db)

    assert len(groups) == 1
    assert groups[0]["cluster_ids"] == [1, 2]
    assert groups[0]["normalized_question"] == "关于研究生方向"


def test_reconcile_moves_sources_closes_duplicate_issues_and_rebuilds_tables(test_db):
    from app.services.question_variant_reconciliation import (
        normalize_original_question,
        reconcile_cross_cluster_variants,
        scan_cross_cluster_variant_groups,
    )

    source_a = {"url": "https://a.example", "company": "A", "round": "一面"}
    source_b = {"url": "https://b.example", "company": "B", "round": "二面"}
    _insert_qb(
        test_db,
        10,
        "研究生方向",
        ["关于研究生方向"],
        sources=[source_a],
        original_sources=[{"question": "关于研究生方向", "sources": [source_a]}],
    )
    _insert_qb(
        test_db,
        11,
        "高并发限流",
        ["怎样做限流？", "关于研究生方向"],
        sources=[source_b],
        original_sources=[
            {"question": "怎样做限流？", "sources": [source_b]},
            {"question": "关于研究生方向", "sources": [source_b]},
        ],
    )
    test_db.execute(
        "INSERT INTO quality_issue "
        "(qb_id, variant_index, issue_type, suggested_action, reason, confidence, "
        "status, source_question, variant_key) VALUES "
        "(11, 1, 'mismerge', 'split', '跨领域', 1.0, 'pending', ?, '1')",
        ("关于研究生方向",),
    )
    test_db.commit()

    key = normalize_original_question("关于研究生方向")
    report = reconcile_cross_cluster_variants(
        test_db,
        {key: 10},
        dry_run=False,
        reviewed_by=99,
    )
    test_db.commit()

    assert report["groups_processed"] == 1
    assert report["issues_closed"] == 1
    source_row = test_db.execute(
        "SELECT original_questions, original_question_sources, frequency, sources "
        "FROM question_bank WHERE id = 10"
    ).fetchone()
    wrong_row = test_db.execute(
        "SELECT original_questions, frequency FROM question_bank WHERE id = 11"
    ).fetchone()
    assert json.loads(source_row[0]) == ["关于研究生方向"]
    assert json.loads(wrong_row[0]) == ["怎样做限流？"]
    assert wrong_row[1] == 1
    assert {item["url"] for item in json.loads(source_row[3])} == {
        "https://a.example",
        "https://b.example",
    }
    assert test_db.execute(
        "SELECT COUNT(*) FROM question_original_items "
        "WHERE question_bank_id = 11 AND question_text = '关于研究生方向'"
    ).fetchone()[0] == 0
    issue_row = test_db.execute(
        "SELECT status, reviewed_by FROM quality_issue WHERE id = 1"
    ).fetchone()
    assert (issue_row["status"], issue_row["reviewed_by"]) == ("rejected", 99)
    assert not scan_cross_cluster_variant_groups(test_db)
    assert test_db.execute(
        "SELECT question_bank_id FROM question_variant_owners "
        "WHERE normalized_question = ?",
        (key,),
    ).fetchone()[0] == 10


def test_reconcile_dry_run_requires_explicit_canonical_and_does_not_write(test_db):
    from app.services.question_variant_reconciliation import (
        normalize_original_question,
        reconcile_cross_cluster_variants,
    )

    _insert_qb(test_db, 20, "题簇一", ["重复题"])
    _insert_qb(test_db, 21, "题簇二", ["重复题"])
    test_db.commit()

    report = reconcile_cross_cluster_variants(
        test_db,
        {},
        dry_run=True,
    )

    key = normalize_original_question("重复题")
    assert report["groups_skipped"] == 1
    assert report["groups"][0]["normalized_question"] == key
    assert test_db.execute(
        "SELECT COUNT(*) FROM question_variant_owners"
    ).fetchone()[0] == 0
    assert test_db.execute(
        "SELECT COUNT(*) FROM quality_issue WHERE status = 'rejected'"
    ).fetchone()[0] == 0


def test_claim_original_question_rejects_other_active_cluster(test_db):
    from app.services.question_variant_reconciliation import (
        VariantOwnershipConflict,
        claim_original_question_owner,
    )

    _insert_qb(test_db, 30, "已有题簇", ["相同原题"])
    _insert_qb(test_db, 31, "新题簇", [])
    test_db.commit()

    with pytest.raises(VariantOwnershipConflict):
        claim_original_question_owner(test_db, "相同原题", 31)


def test_apply_matched_rejects_cross_cluster_duplicate(test_db):
    from app.services.pipeline.writer import apply_matched
    from app.services.question_variant_reconciliation import VariantOwnershipConflict

    _insert_qb(test_db, 40, "已有题簇", ["相同原题"])
    _insert_qb(test_db, 41, "目标题簇", [])
    test_db.commit()

    with pytest.raises(VariantOwnershipConflict):
        apply_matched(
            test_db,
            [{"cluster_id": 41, "question": "相同原题", "url": "https://x.example"}],
            "后端开发",
            {},
        )


def test_sync_normalized_tables_removes_orphaned_provenance_entries(test_db):
    """归并移除原题后，遗留的 JSON 来源条目也必须被清掉。"""
    from app.services.question_variant_reconciliation import _sync_normalized_tables

    _insert_qb(
        test_db,
        50,
        "规范题",
        ["保留题"],
        original_sources=[
            {"question": "保留题", "sources": []},
            {"question": "已移除题", "sources": [{"url": "https://orphan.example"}]},
        ],
    )
    test_db.commit()

    _sync_normalized_tables(test_db, 50)

    row = test_db.execute(
        "SELECT original_question_sources FROM question_bank WHERE id = 50"
    ).fetchone()
    assert json.loads(row[0]) == [{"question": "保留题", "sources": []}]
    assert test_db.execute(
        "SELECT 1 FROM question_original_item_sources WHERE url = 'https://orphan.example'"
    ).fetchone() is None

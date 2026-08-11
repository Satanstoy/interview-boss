"""interview_merge_service：同签名重复公共面经的列表与合并。

只处理公共面经（owner_id IS NULL），私有面经绝不触碰。合并软删可恢复。
"""

import json

import pytest

from fastapi import HTTPException

from app.services.interview_merge_service import (
    list_duplicate_groups,
    merge_duplicate_group,
    merge_all_duplicate_groups,
)


def _insert_user(conn, user_id):
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, email, password_hash) "
        "VALUES (?, ?, ?, 'x')",
        (user_id, f"user{user_id}", f"u{user_id}@test.com"),
    )


def _insert_interview(conn, url, sig, owner_id=None, company="测试公司"):
    if owner_id is not None:
        _insert_user(conn, owner_id)
    cur = conn.execute(
        "INSERT INTO interview (url, url_signature, company, round, owner_id, status) "
        "VALUES (?, ?, ?, '一面', ?, 'approved')",
        (url, sig, company, owner_id),
    )
    return cur.lastrowid


def _insert_jd(conn, url, sig, owner_id=None):
    if owner_id is not None:
        _insert_user(conn, owner_id)
    cur = conn.execute(
        "INSERT INTO jd (url, url_signature, owner_id, status) "
        "VALUES (?, ?, ?, 'approved')",
        (url, sig, owner_id),
    )
    return cur.lastrowid


def _insert_qb(conn, qb_id, sources_json="[]", oqs_json="[]", owner_id=None):
    if owner_id is not None:
        _insert_user(conn, owner_id)
    conn.execute(
        "INSERT INTO question_bank (id, question, sources, original_questions, "
        "original_question_sources, frequency, owner_id, status) "
        "VALUES (?, '测试题', ?, '[]', ?, 1, ?, 'approved')",
        (qb_id, sources_json, oqs_json, owner_id),
    )


def _insert_detail(conn, interview_id, question, owner_id=None):
    conn.execute(
        "INSERT INTO questions_detail (interview_id, question, url, owner_id, status) "
        "VALUES (?, ?, 'http://x', ?, 'approved')",
        (interview_id, question, owner_id),
    )


def _insert_qs(conn, qb_id, url):
    conn.execute(
        "INSERT INTO question_sources (question_bank_id, url) VALUES (?, ?)",
        (qb_id, url),
    )


# ── list_duplicate_groups ──


def test_list_duplicate_groups_only_public(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    _insert_interview(test_db, "http://b.com/y?a=1", "nc:2", owner_id=99)
    _insert_interview(test_db, "https://b.com/y?a=2", "nc:2", owner_id=99)
    test_db.commit()
    groups = list_duplicate_groups(test_db, "interview")
    assert len(groups) == 1
    g = groups[0]
    assert g["signature"] == "nc:1"
    assert g["count"] == 2
    assert g["keep_id"] == 1
    assert len(g["records"]) == 2


def test_list_duplicate_groups_jd(test_db):
    _insert_jd(test_db, "http://b.com/j", "generic:b.com/j")
    _insert_jd(test_db, "http://b.com/j?p=2", "generic:b.com/j")
    test_db.commit()
    groups = list_duplicate_groups(test_db, "jd")
    assert len(groups) == 1
    assert groups[0]["signature"] == "generic:b.com/j"


# ── merge_duplicate_group dry_run ──


def test_merge_dry_run_no_change(test_db):
    i1 = _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    i2 = _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    test_db.commit()
    result = merge_duplicate_group(test_db, "nc:1", dry_run=True)
    assert result["dry_run"] is True
    assert result["keep_id"] == i1
    assert result["merged_count"] == 1
    # DB 无变化
    active = test_db.execute(
        "SELECT COUNT(*) FROM interview WHERE deleted_at IS NULL"
    ).fetchone()[0]
    assert active == 2


# ── merge_duplicate_group 真实执行 ──


def test_merge_real_keeps_min_soft_deletes_rest(test_db):
    i1 = _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    i2 = _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    test_db.commit()
    result = merge_duplicate_group(test_db, "nc:1", dry_run=False)
    assert result["keep_id"] == i1
    assert result["merged_count"] == 1
    assert result["actions"]["interviews_soft_deleted"] == 1
    # i1 active, i2 soft-deleted
    assert test_db.execute("SELECT deleted_at FROM interview WHERE id = ?", (i1,)).fetchone()[0] is None
    assert test_db.execute("SELECT deleted_at FROM interview WHERE id = ?", (i2,)).fetchone()[0] is not None


def test_merge_does_not_touch_private(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    _insert_interview(test_db, "http://p.com/y?a=1", "nc:2", owner_id=99)
    _insert_interview(test_db, "https://p.com/y?a=2", "nc:2", owner_id=99)
    test_db.commit()
    # 合并 nc:1 不应影响私有 nc:2
    merge_duplicate_group(test_db, "nc:1", dry_run=False)
    private_active = test_db.execute(
        "SELECT COUNT(*) FROM interview WHERE url_signature = 'nc:2' AND deleted_at IS NULL"
    ).fetchone()[0]
    assert private_active == 2


def test_merge_rehangs_and_dedupes_details(test_db):
    i1 = _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    i2 = _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    _insert_detail(test_db, i1, "问题一")
    _insert_detail(test_db, i2, "问题一")   # 与 keep 重复
    _insert_detail(test_db, i2, "问题二")   # 仅 drop 有
    test_db.commit()
    merge_duplicate_group(test_db, "nc:1", dry_run=False)
    # 所有 active detail 挂到 i1
    details = test_db.execute(
        "SELECT interview_id, question FROM questions_detail WHERE deleted_at IS NULL"
    ).fetchall()
    assert all(r[0] == i1 for r in details)
    # 去重后 2 条（问题一 + 问题二）
    assert len(details) == 2
    assert {r[1] for r in details} == {"问题一", "问题二"}


def test_merge_normalizes_sources_only_public_qb(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    _insert_qb(test_db, 1, sources_json='[{"url": "https://a.com/x?a=2", "company": "", "round": ""}]')
    _insert_qb(test_db, 2, sources_json='[{"url": "https://a.com/x?a=2", "company": "", "round": ""}]', owner_id=99)
    _insert_qs(test_db, 1, "https://a.com/x?a=2")
    _insert_qs(test_db, 2, "https://a.com/x?a=2")
    test_db.commit()
    merge_duplicate_group(test_db, "nc:1", dry_run=False)
    # 公共 qb 来源归一为 keep_url；私有 qb 不动
    pub_sources = test_db.execute(
        "SELECT url FROM question_sources WHERE question_bank_id = 1 AND deleted_at IS NULL"
    ).fetchall()
    assert [r[0] for r in pub_sources] == ["http://a.com/x?a=1"]
    priv_sources = test_db.execute(
        "SELECT url FROM question_sources WHERE question_bank_id = 2 AND deleted_at IS NULL"
    ).fetchall()
    assert [r[0] for r in priv_sources] == ["https://a.com/x?a=2"]


def test_merge_syncs_qb_json_columns(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    _insert_qb(test_db, 1, sources_json='[{"url": "https://a.com/x?a=2", "company": "", "round": ""}]')
    test_db.commit()
    merge_duplicate_group(test_db, "nc:1", dry_run=False)
    row = test_db.execute("SELECT sources FROM question_bank WHERE id = 1").fetchone()
    urls = [s["url"] for s in json.loads(row[0])]
    assert urls == ["http://a.com/x?a=1"]


# ── jd 合并 ──


def test_merge_jd_soft_deletes_duplicates(test_db):
    j1 = _insert_jd(test_db, "http://b.com/j", "generic:b.com/j")
    j2 = _insert_jd(test_db, "http://b.com/j?p=2", "generic:b.com/j")
    test_db.commit()
    result = merge_duplicate_group(test_db, "generic:b.com/j", table="jd", dry_run=False)
    assert result["keep_id"] == j1
    assert result["actions"]["records_soft_deleted"] == 1
    assert test_db.execute("SELECT deleted_at FROM jd WHERE id = ?", (j1,)).fetchone()[0] is None
    assert test_db.execute("SELECT deleted_at FROM jd WHERE id = ?", (j2,)).fetchone()[0] is not None


# ── 边界 ──


def test_merge_missing_signature_404(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    test_db.commit()
    with pytest.raises(HTTPException) as exc:
        merge_duplicate_group(test_db, "nc:999", dry_run=False)
    assert exc.value.status_code == 404


def test_merge_all_count(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    _insert_interview(test_db, "http://c.com/z?a=1", "nc:3")
    _insert_interview(test_db, "https://c.com/z?a=2", "nc:3")
    test_db.commit()
    result = merge_all_duplicate_groups(test_db, "interview", dry_run=False)
    assert result["merged_count"] == 2
    assert len(result["results"]) == 2


def test_public_url_signature_unique_indexes_are_safe_to_enable(test_db):
    from app.db.migrations.sources import ensure_public_url_signature_unique_indexes

    result = ensure_public_url_signature_unique_indexes(test_db)

    assert result["skipped"] == []
    assert result["interview"] is True
    assert result["jd"] is True
    interview_indexes = {
        row[1] for row in test_db.execute("PRAGMA index_list('interview')").fetchall()
    }
    assert "uq_interview_public_url_signature" in interview_indexes

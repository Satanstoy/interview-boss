"""AC-005 / UR-005：原题引用、归属与失效语义。"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.question_resolution import (
    ResolutionConflict,
    get_current_resolution,
    invalidate_resolutions_for_canonical,
    list_mine_canonical_ids,
    record_resolution,
    resolution_source_visibility,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    for uid in (101, 102):
        conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    # 公共规范题
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status, frequency, sources, original_questions) "
        "VALUES (900, 'TCP 三次握手', '计算机网络', 'TCP', NULL, 'approved', 2, "
        '\'[{"url": "https://a.example.com/1"}]\', \'["TCP 三次握手"]\')'
    )
    # 101 的私人规范题
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status, frequency, sources, original_questions) "
        "VALUES (901, '个人优缺点', 'HR', 'HR', 101, 'approved', 1, '[]', '[]')"
    )
    for detail_id, interview_id in ((1, 1), (2, 2)):
        conn.execute(
            "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2) "
            "VALUES (?, ?, 'TCP 三次握手', '计算机网络', 'TCP')",
            (detail_id, interview_id),
        )
    conn.commit()
    return conn


def _public_snapshot(conn, canonical_id=900):
    row = conn.execute(
        "SELECT frequency, sources, original_questions FROM question_bank WHERE id = ?",
        (canonical_id,),
    ).fetchone()
    return row["frequency"], row["sources"], row["original_questions"]


def test_private_reference_to_public_canonical_does_not_touch_public_counts():
    conn = _db()
    before = _public_snapshot(conn)
    record_resolution(
        conn,
        detail_id=1,
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=900,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    assert _public_snapshot(conn) == before, "私人引用不得改公共 sources/frequency"
    resolution = get_current_resolution(conn, detail_id=1)
    assert resolution["occurrence_scope"] == "private"
    assert resolution["occurrence_owner_id"] == 101
    assert resolution["canonical_id"] == 900
    conn.close()


def test_mine_view_shows_referenced_public_canonical_only_to_owner():
    conn = _db()
    record_resolution(
        conn,
        detail_id=1,
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=900,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    assert 900 in list_mine_canonical_ids(conn, user_id=101)
    assert 901 in list_mine_canonical_ids(conn, user_id=101)
    # 102 未引用：既看不到关联，也看不到别人的私人来源
    assert 900 not in list_mine_canonical_ids(conn, user_id=102)
    mine = resolution_source_visibility(conn, user_id=101, canonical_id=900)
    other = resolution_source_visibility(conn, user_id=102, canonical_id=900)
    assert mine["has_own_source"] is True and mine["visible_detail_ids"] == [1]
    assert other["has_own_source"] is False and other["visible_detail_ids"] == []
    conn.close()


def test_public_canonical_invalidation_keeps_original_and_allows_relink():
    conn = _db()
    record_resolution(
        conn,
        detail_id=1,
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=900,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    invalidated = invalidate_resolutions_for_canonical(
        conn, canonical_id=900, reason="public_canonical_deleted"
    )
    assert invalidated == 1
    assert get_current_resolution(conn, detail_id=1) is None
    # 原题仍在
    assert conn.execute("SELECT COUNT(*) FROM questions_detail WHERE id = 1").fetchone()[0] == 1
    # 可以重新关联到自己的私人题
    relinked = record_resolution(
        conn,
        detail_id=1,
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=901,
        canonical_scope="private",
        status="created",
        pipeline_version="v1",
    )
    assert relinked["canonical_id"] == 901
    assert get_current_resolution(conn, detail_id=1)["canonical_id"] == 901
    conn.close()


def test_only_one_current_resolution_per_detail():
    conn = _db()
    record_resolution(
        conn,
        detail_id=1,
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=900,
        canonical_scope="public",
        status="matched",
        pipeline_version="v1",
    )
    # 不经 helper 直接插入第二条当前 resolution 必须被数据库拒绝
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO question_resolutions (detail_id, occurrence_scope, "
            "occurrence_owner_id, canonical_id, canonical_scope, status, pipeline_version) "
            "VALUES (1, 'private', 101, 901, 'private', 'matched', 'v1')"
        )
    conn.close()


def test_scope_rules_reject_cross_owner_and_cross_scope():
    conn = _db()
    # 私人原题不能引用别人的私人题
    with pytest.raises(ResolutionConflict):
        record_resolution(
            conn,
            detail_id=2,
            occurrence_scope="private",
            occurrence_owner_id=102,
            canonical_id=901,
            canonical_scope="private",
            status="matched",
            pipeline_version="v1",
        )
    # 公共原题不能引用私人题
    with pytest.raises(ResolutionConflict):
        record_resolution(
            conn,
            detail_id=2,
            occurrence_scope="public",
            occurrence_owner_id=None,
            canonical_id=901,
            canonical_scope="private",
            status="matched",
            pipeline_version="v1",
        )
    # 归属不自洽直接拒绝
    with pytest.raises(ValueError):
        record_resolution(
            conn,
            detail_id=2,
            occurrence_scope="public",
            occurrence_owner_id=102,
            canonical_id=900,
            canonical_scope="public",
            status="matched",
            pipeline_version="v1",
        )
    conn.close()


def test_matched_requires_canonical_but_failed_does_not():
    conn = _db()
    with pytest.raises(ValueError):
        record_resolution(
            conn,
            detail_id=1,
            occurrence_scope="private",
            occurrence_owner_id=101,
            canonical_id=None,
            canonical_scope="public",
            status="matched",
            pipeline_version="v1",
        )
    failed = record_resolution(
        conn,
        detail_id=1,
        occurrence_scope="private",
        occurrence_owner_id=101,
        canonical_id=None,
        canonical_scope=None,
        status="failed",
        pipeline_version="v1",
        reason="MODEL_AUTH_INVALID",
    )
    assert failed["status"] == "failed"
    conn.close()

"""来源健康检查：同签名重复面经 / internal:// 增长 / JSON 双写不一致。

持续监控缺口：复发要能在 cron 里被发现，而不是等用户报障。
"""

import json

import pytest

from app.services.source_health import run_source_health_checks


def _insert_user(test_db, user_id):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, email, password_hash) "
        "VALUES (?, ?, ?, 'x')",
        (user_id, f"user{user_id}", f"u{user_id}@test.com"),
    )


def _insert_interview(test_db, url, sig, deleted_at=None, owner_id=None):
    if owner_id is not None:
        _insert_user(test_db, owner_id)
    test_db.execute(
        "INSERT INTO interview (url, url_signature, company, round, owner_id, status, deleted_at) "
        "VALUES (?, ?, '测试公司', '一面', ?, 'approved', ?)",
        (url, sig, owner_id, deleted_at),
    )


def _insert_qb(test_db, sources_json="[]", oq_json="[]", oqs_json="[]"):
    cur = test_db.execute(
        "INSERT INTO question_bank (question, sources, original_questions, original_question_sources, frequency) "
        "VALUES ('测试题', ?, ?, ?, 1)",
        (sources_json, oq_json, oqs_json),
    )
    return cur.lastrowid


# ── 同签名重复面经 ──


def test_duplicate_signature_detected_in_interview(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    test_db.commit()
    report = run_source_health_checks(test_db)
    groups = report["duplicate_signature_groups"]["interview"]
    assert len(groups) == 1
    assert groups[0]["signature"] == "nc:1"
    assert groups[0]["count"] == 2


def test_duplicate_signature_ignores_deleted(test_db):
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1", deleted_at="2026-01-01 00:00:00")
    test_db.commit()
    report = run_source_health_checks(test_db)
    assert report["duplicate_signature_groups"]["interview"] == []


def test_duplicate_signature_detected_in_jd(test_db):
    test_db.execute(
        "INSERT INTO jd (url, url_signature) VALUES ('http://b.com/j', 'generic:b.com/j')"
    )
    test_db.execute(
        "INSERT INTO jd (url, url_signature) VALUES ('http://b.com/j?p=2', 'generic:b.com/j')"
    )
    test_db.commit()
    report = run_source_health_checks(test_db)
    assert len(report["duplicate_signature_groups"]["jd"]) == 1


def test_duplicate_signature_private_excluded(test_db):
    """私有面经的同签名重复不进重复组（仅统计公共面经 owner_id IS NULL）"""
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")                 # 公共
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")                # 公共
    _insert_interview(test_db, "http://b.com/y?a=1", "nc:2", owner_id=99)    # 私有
    _insert_interview(test_db, "https://b.com/y?a=2", "nc:2", owner_id=99)   # 私有
    test_db.commit()
    report = run_source_health_checks(test_db)
    groups = report["duplicate_signature_groups"]["interview"]
    assert len(groups) == 1
    assert groups[0]["signature"] == "nc:1"


# ── internal:// 增长 ──


def test_internal_counts_report(test_db):
    _insert_interview(test_db, "internal://abc", "")
    qb_id = _insert_qb(test_db)
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url) VALUES (?, 'internal://def')",
        (qb_id,),
    )
    test_db.commit()
    report = run_source_health_checks(test_db)
    assert report["internal"]["interview"] == 1
    assert report["internal"]["jd"] == 0
    assert report["internal"]["question_sources"] == 1


def test_internal_new_detected_against_baseline(test_db, tmp_path):
    baseline = str(tmp_path / "source_health_baseline.json")
    _insert_interview(test_db, "internal://old", "")
    test_db.commit()
    first = run_source_health_checks(test_db, baseline_path=baseline)
    assert first["internal"]["new_urls"] == []

    _insert_interview(test_db, "internal://brand-new", "")
    test_db.commit()
    second = run_source_health_checks(test_db, baseline_path=baseline)
    assert "interview:internal://brand-new" in second["internal"]["new_urls"]
    assert "interview:internal://old" not in second["internal"]["new_urls"]


# ── JSON 双写不一致 ──


def test_dual_write_sources_mismatch(test_db):
    qb_id = _insert_qb(test_db, sources_json='[{"url": "http://x.com/a", "company": "", "round": ""}]')
    test_db.commit()
    report = run_source_health_checks(test_db)
    qb_mismatches = [m for m in report["dual_write_mismatches"] if m["qb_id"] == qb_id]
    assert any(m["field"] == "sources" for m in qb_mismatches)


def test_dual_write_sources_consistent(test_db):
    qb_id = _insert_qb(test_db, sources_json='[{"url": "http://x.com/a", "company": "", "round": ""}]')
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round) "
        "VALUES (?, 'http://x.com/a', '', '')",
        (qb_id,),
    )
    test_db.commit()
    report = run_source_health_checks(test_db)
    qb_mismatches = [m for m in report["dual_write_mismatches"] if m["qb_id"] == qb_id]
    assert all(m["field"] != "sources" for m in qb_mismatches)


def test_dual_write_original_questions_mismatch(test_db):
    qb_id = _insert_qb(test_db, oq_json='["问题一", "问题二"]')
    test_db.commit()
    report = run_source_health_checks(test_db)
    qb_mismatches = [m for m in report["dual_write_mismatches"] if m["qb_id"] == qb_id]
    assert any(m["field"] == "original_questions" for m in qb_mismatches)


def test_healthy_state_ok_flag(test_db):
    _insert_interview(test_db, "http://a.com/x", "nc:1")
    test_db.commit()
    report = run_source_health_checks(test_db)
    assert report["ok"] is True


# ── 同 qb 同笔记 URL 变体 ──


def test_per_qb_url_variants_detected(test_db):
    """同一 qb 内同笔记（xsec_token 不同）多个 URL → 变体告警"""
    qb_id = _insert_qb(test_db)
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url) VALUES (?, ?)",
        (qb_id, "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=A"),
    )
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url) VALUES (?, ?)",
        (qb_id, "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=B"),
    )
    test_db.commit()
    report = run_source_health_checks(test_db)
    variants = [v for v in report["per_qb_url_variants"] if v["qb_id"] == qb_id]
    assert len(variants) == 1
    assert variants[0]["note_key"] == "xhs:69ebf7ec000000001f0075ba"
    assert variants[0]["url_count"] == 2
    assert report["ok"] is False


def test_per_qb_no_variants_healthy(test_db):
    """同 qb 不同笔记 URL → 不是变体"""
    urls = [
        "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=A",
        "https://www.nowcoder.com/discuss/123",
    ]
    qb_id = _insert_qb(test_db, sources_json=json.dumps([{"url": u} for u in urls]))
    for u in urls:
        test_db.execute(
            "INSERT INTO question_sources (question_bank_id, url) VALUES (?, ?)",
            (qb_id, u),
        )
    test_db.commit()
    report = run_source_health_checks(test_db)
    assert report["per_qb_url_variants"] == []
    assert report["ok"] is True


# ── 孤儿 questions_detail ──


def test_orphan_details_counted(test_db):
    """interview 不存在的 detail → 孤儿计数（不参与 ok 判定）"""
    test_db.execute(
        "INSERT INTO questions_detail (interview_id, question) VALUES (99999, '孤儿题')"
    )
    test_db.commit()
    report = run_source_health_checks(test_db)
    assert report["orphan_details"] >= 1
    assert report["ok"] is True  # 孤儿只提示不阻断

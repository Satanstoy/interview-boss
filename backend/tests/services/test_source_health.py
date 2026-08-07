"""来源健康检查：同签名重复面经 / internal:// 增长 / JSON 双写不一致。

持续监控缺口：复发要能在 cron 里被发现，而不是等用户报障。
"""

import json

import pytest

from app.services.source_health import run_source_health_checks


def _insert_interview(test_db, url, sig, deleted_at=None):
    test_db.execute(
        "INSERT INTO interview (url, url_signature, company, round, owner_id, status, deleted_at) "
        "VALUES (?, ?, '测试公司', '一面', NULL, 'approved', ?)",
        (url, sig, deleted_at),
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

"""Public rebuild must only reuse answers from the public approved bank."""

from __future__ import annotations

from unittest.mock import patch

import pytest


JOB_POSITION = "后端开发"


def test_public_rebuild_answer_cache_excludes_private_and_pending_rows(test_db, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    from app.worker import _load_public_rebuild_answer_cache

    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (2, 'private-owner', 'x', 0)"
    )
    test_db.executemany(
        "INSERT INTO question_bank "
        "(question, ai_answer, answer_sources, job_position, owner_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("同一道题", "公共答案", "public-source", JOB_POSITION, None, "approved"),
            ("个人题答案", "个人答案", "private-source", JOB_POSITION, 2, "approved"),
            ("待审题答案", "待审答案", "pending-source", JOB_POSITION, None, "pending"),
        ],
    )
    test_db.commit()

    answer_cache = _load_public_rebuild_answer_cache(test_db, JOB_POSITION)

    assert answer_cache == {"同一道题": {"answer": "公共答案", "sources": "public-source"}}


def test_cleanup_by_interview_id_keeps_same_url_public_contribution(test_db):
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_kwargs: url,
    ):
        from app.db.operations import cleanup_interview_question_bank_sources

    source_url = "https://same.example/interview"
    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (7, 'private-owner', 'x', 0)"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) "
        "VALUES (101, ?, NULL, 'approved', ?), (102, ?, 7, 'approved', ?)",
        (source_url, JOB_POSITION, source_url, JOB_POSITION),
    )
    source_json = '[{"url": "%s"}]' % source_url
    test_db.execute(
        "INSERT INTO question_bank "
        "(id, question, frequency, sources, owner_id, status, job_position) "
        "VALUES (801, '公共簇', 1, ?, NULL, 'approved', ?), "
        "(802, '个人簇', 1, ?, 7, 'approved', ?), "
        "(803, '无关公共零频题', 0, '[]', NULL, 'approved', ?)",
        (source_json, JOB_POSITION, source_json, JOB_POSITION, JOB_POSITION),
    )
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url) VALUES (801, ?), (802, ?)",
        (source_url, source_url),
    )
    test_db.commit()

    test_db.execute("BEGIN")
    cleanup_interview_question_bank_sources(test_db.cursor(), 102)
    test_db.commit()

    public_row = test_db.execute("SELECT deleted_at FROM question_bank WHERE id = 801").fetchone()
    private_row = test_db.execute("SELECT deleted_at FROM question_bank WHERE id = 802").fetchone()
    unrelated_public_row = test_db.execute(
        "SELECT deleted_at FROM question_bank WHERE id = 803"
    ).fetchone()
    assert public_row["deleted_at"] is None
    assert private_row["deleted_at"] is not None
    assert unrelated_public_row["deleted_at"] is None


@pytest.mark.asyncio
async def test_same_url_public_and_other_private_details_stay_out_of_list_and_insights(
    test_db,
):
    with patch(
        "app.core.outbound_url.assert_safe_outbound_url_sync",
        side_effect=lambda url, **_kwargs: url,
    ):
        from app.routers.data import get_data
        from app.services.insights import build_insights_snapshot

    source_url = "https://same.example/list-and-stats"
    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES "
        "(7, 'list-owner', 'x', 0), (8, 'other-owner', 'x', 0)"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) VALUES "
        "(201, ?, NULL, 'approved', ''), (202, ?, 8, 'approved', '')",
        (source_url, source_url),
    )
    test_db.execute(
        "INSERT INTO questions_detail "
        "(id, interview_id, url, question, cat2, deleted_at, job_position) VALUES "
        "(211, 201, ?, '公共明细', '公共主题', NULL, ''), "
        "(212, 202, ?, '他人私密明细', '他人私密主题', NULL, '')",
        (source_url, source_url),
    )
    test_db.commit()

    async def run_db_sync(func):
        return func()

    with patch("app.routers.data.run_db", side_effect=run_db_sync):
        listed = await get_data("tagged", page=1, page_size=100, user={"id": 7})

    assert listed["total"] == 1
    assert [item["题目"] for item in listed["items"]] == ["公共明细"]

    snapshot = build_insights_snapshot({"id": 7})
    topics = {item["topic"] for item in snapshot["high_frequency"]}
    assert "公共主题" in topics
    assert "他人私密主题" not in topics

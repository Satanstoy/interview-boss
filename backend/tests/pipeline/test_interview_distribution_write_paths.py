"""Every interview-detail writer must preserve linked distribution facts."""

from unittest.mock import AsyncMock, patch

import pytest


def _tagged_row(question, cat1, cat2="", tags="", diff_tag="L2"):
    return [
        "https://example.test/interview",
        "测试公司",
        "一面",
        question,
        cat1,
        cat2,
        tags,
        diff_tag,
    ]


def _refresh_status(conn, job_position):
    return conn.execute(
        "SELECT status FROM interview_distribution_refresh_jobs "
        "WHERE scope = 'public_job_position' AND job_position = ?",
        (job_position,),
    ).fetchone()["status"]


def test_submit_interview_links_details_types_them_and_marks_public_scope_stale(test_db):
    from app.db.operations import submit_interview_txn_tag_only

    interview_id = submit_interview_txn_tag_only(
        "https://example.test/interview",
        {"公司": "测试公司", "面试轮次": "一面", "考察重点": "算法", "难易程度": "中等"},
        "手撕 LRU Cache",
        "2026Q3",
        None,
        "approved",
        "Agent开发",
        [_tagged_row("手撕 LRU Cache", "E.算法与数据结构", "E2.算法手撕")],
    )

    detail = test_db.execute(
        "SELECT interview_id, question_type, dimension FROM questions_detail"
    ).fetchone()

    assert detail["interview_id"] == interview_id
    assert detail["question_type"] == "algorithm_coding"
    assert detail["dimension"] == "knowledge_probe"
    assert _refresh_status(test_db, "Agent开发") == "pending"


def test_replace_details_only_replaces_the_known_interview_and_requeues_stats(test_db):
    from app.db.operations import _replace_details_txn, submit_interview_txn_tag_only

    interview_id = submit_interview_txn_tag_only(
        "https://example.test/interview",
        {"公司": "测试公司", "面试轮次": "一面"},
        "手撕 LRU Cache",
        "2026Q3",
        None,
        "approved",
        "Agent开发",
        [_tagged_row("手撕 LRU Cache", "E.算法与数据结构")],
    )
    other_id = submit_interview_txn_tag_only(
        "https://example.test/other",
        {"公司": "测试公司", "面试轮次": "二面"},
        "Redis",
        "2026Q3",
        None,
        "approved",
        "Agent开发",
        [_tagged_row("Redis", "C.基础工程能力")],
    )

    _replace_details_txn(
        test_db.cursor(),
        interview_id,
        "https://example.test/interview",
        [_tagged_row("请介绍一个你负责过的项目", "A.项目经验与设计")],
        "Agent开发",
    )

    replaced = test_db.execute(
        "SELECT question_type FROM questions_detail WHERE interview_id = ?",
        (interview_id,),
    ).fetchone()["question_type"]
    untouched = test_db.execute(
        "SELECT question_type FROM questions_detail WHERE interview_id = ?",
        (other_id,),
    ).fetchone()["question_type"]
    assert replaced == "project_followup"
    assert untouched == "knowledge_probe"
    assert _refresh_status(test_db, "Agent开发") == "pending"


@pytest.mark.asyncio
async def test_pipeline_writer_uses_known_interview_id_and_requeues_stats(test_db, monkeypatch):
    import app.services.pipeline.writer as writer

    async def _run_on_test_connection(function):
        return function()

    monkeypatch.setattr(writer, "_run_db", _run_on_test_connection)

    with patch(
        "app.services.submit_service.tag_questions_batch",
        new=AsyncMock(return_value=[_tagged_row("二分查找", "E.算法与数据结构")]),
    ):
        test_db.execute(
            """
            INSERT INTO interview (url, company, round, focus, questions_list, difficulty, owner_id, status, job_position)
            VALUES ('https://example.test/interview', '测试公司', '一面', '', '二分查找', '', NULL, 'approved', 'Agent开发')
            """
        )
        interview_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
        test_db.commit()
        await writer.tag_and_write_details(
            "https://example.test/interview",
            "测试公司",
            "一面",
            "二分查找",
            "Agent开发",
            None,
            interview_id=interview_id,
        )

    detail = test_db.execute(
        "SELECT interview_id, question_type FROM questions_detail"
    ).fetchone()
    assert (detail["interview_id"], detail["question_type"]) == (interview_id, "algorithm_coding")
    assert _refresh_status(test_db, "Agent开发") == "pending"


def test_retyping_a_linked_detail_updates_its_fact_and_marks_its_scope_stale(test_db):
    from app.db.operations import (
        _retype_distribution_details_txn,
        submit_interview_txn_tag_only,
    )

    interview_id = submit_interview_txn_tag_only(
        "https://example.test/interview",
        {"公司": "测试公司", "面试轮次": "一面"},
        "Redis",
        "2026Q3",
        None,
        "approved",
        "Agent开发",
        [_tagged_row("Redis", "C.基础工程能力")],
    )
    detail_id = test_db.execute(
        "SELECT id FROM questions_detail WHERE interview_id = ?", (interview_id,)
    ).fetchone()["id"]
    test_db.execute(
        "UPDATE questions_detail SET cat1 = 'E.算法与数据结构' WHERE id = ?", (detail_id,)
    )

    _retype_distribution_details_txn(test_db.cursor(), [detail_id])

    assert test_db.execute(
        "SELECT question_type FROM questions_detail WHERE id = ?", (detail_id,)
    ).fetchone()["question_type"] == "algorithm_coding"
    assert _refresh_status(test_db, "Agent开发") == "pending"

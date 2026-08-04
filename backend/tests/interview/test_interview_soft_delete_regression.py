"""面经软删除回归测试。

这些测试使用 conftest 的真实 SQLite migration，而不是源码正则或空的
MagicMock，覆盖线上曾出现的“来源已删、面经仍在”的半删除状态。
"""

import json

import pytest

from app.routers import data


ADMIN = {"id": 1, "is_admin": 1}


def _insert_interview(conn, url: str, company: str = "测试公司") -> int:
    cursor = conn.execute(
        "INSERT INTO interview "
        "(url, company, round, focus, questions_list, difficulty, owner_id, status, job_position) "
        "VALUES (?, ?, '一面', '未提供', ?, '中等', NULL, 'approved', '后端开发')",
        (url, company, json.dumps(["题目A", "题目B"], ensure_ascii=False)),
    )
    return cursor.lastrowid


def _insert_detail(conn, interview_id: int, url: str, question: str) -> int:
    cursor = conn.execute(
        "INSERT INTO questions_detail "
        "(interview_id, url, company, round, question, deleted_at) "
        "VALUES (?, ?, '测试公司', '一面', ?, NULL)",
        (interview_id, url, question),
    )
    return cursor.lastrowid


def _insert_question_bank_source(conn, url: str) -> int:
    oqs = [
        {"question": "题目A", "sources": [{"url": url, "company": "测试公司", "round": "一面"}]},
        {"question": "题目B", "sources": [{"url": url, "company": "测试公司", "round": "一面"}]},
    ]
    cursor = conn.execute(
        "INSERT INTO question_bank "
        "(question, frequency, sources, original_questions, original_question_sources, owner_id, status) "
        "VALUES ('聚类题', 2, ?, ?, ?, NULL, 'approved')",
        (
            json.dumps([{"url": url, "company": "测试公司", "round": "一面"}], ensure_ascii=False),
            json.dumps(["题目A", "题目B"], ensure_ascii=False),
            json.dumps(oqs, ensure_ascii=False),
        ),
    )
    qb_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round, deleted_at) "
        "VALUES (?, ?, '测试公司', '一面', CURRENT_TIMESTAMP)",
        (qb_id, url),
    )
    item_ids = []
    for question in ("题目A", "题目B"):
        item = conn.execute(
            "INSERT INTO question_original_items (question_bank_id, question_text) VALUES (?, ?)",
            (qb_id, question),
        )
        item_ids.append(item.lastrowid)
        conn.execute(
            "INSERT INTO question_original_item_sources "
            "(original_item_id, url, company, round) VALUES (?, ?, '测试公司', '一面')",
            (item.lastrowid, url),
        )

    position = conn.execute("SELECT id FROM job_positions LIMIT 1").fetchone()
    if position is None:
        position = (conn.execute("INSERT INTO job_positions (name) VALUES ('后端开发')").lastrowid,)
    conn.execute(
        "INSERT INTO question_position (question_id, position_id) VALUES (?, ?)",
        (qb_id, position[0]),
    )
    conn.commit()
    return qb_id


async def _delete_interview(monkeypatch, record_id: int):
    async def run_inline(func):
        return func()

    monkeypatch.setattr(data, "run_db", run_inline)
    return await data.delete_data("interview", record_id, ADMIN)


@pytest.mark.asyncio
async def test_delete_repairs_partial_source_cleanup_and_is_idempotent(test_db, monkeypatch):
    """来源已被旧逻辑软删时，删除按钮仍应完成主记录和题库清理，且可重试。"""
    url = "internal://soft-delete-regression"
    interview_id = _insert_interview(test_db, url, "测试软删除公司3")
    detail_ids = [_insert_detail(test_db, interview_id, url, q) for q in ("题目A", "题目B")]
    qb_id = _insert_question_bank_source(test_db, url)

    result = await _delete_interview(monkeypatch, interview_id)
    assert result == {"status": "success"}

    interview = test_db.execute(
        "SELECT deleted_at FROM interview WHERE id = ?", (interview_id,)
    ).fetchone()
    assert interview["deleted_at"] is not None
    assert all(
        test_db.execute("SELECT deleted_at FROM questions_detail WHERE id = ?", (detail_id,)).fetchone()["deleted_at"]
        is not None
        for detail_id in detail_ids
    )

    qb = test_db.execute(
        "SELECT deleted_at FROM question_bank WHERE id = ?", (qb_id,)
    ).fetchone()
    assert qb["deleted_at"] is not None
    assert test_db.execute(
        "SELECT 1 FROM question_position WHERE question_id = ?", (qb_id,)
    ).fetchone() is None

    # 主记录已经是 deleted_at 非空时，重复点击仍会重试派生数据清理，而不是 404。
    retry = await _delete_interview(monkeypatch, interview_id)
    assert retry == {"status": "success"}


@pytest.mark.asyncio
async def test_delete_scopes_details_to_the_selected_interview(test_db, monkeypatch):
    """相同 URL 的两条面经不能因 URL 级联而互相删除题目明细。"""
    url = "internal://same-url"
    first_id = _insert_interview(test_db, url, "公司A")
    second_id = _insert_interview(test_db, url, "公司B")
    first_detail = _insert_detail(test_db, first_id, url, "题目A")
    second_detail = _insert_detail(test_db, second_id, url, "题目B")
    test_db.commit()

    await _delete_interview(monkeypatch, first_id)

    assert test_db.execute(
        "SELECT deleted_at FROM questions_detail WHERE id = ?", (first_detail,)
    ).fetchone()["deleted_at"] is not None
    assert test_db.execute(
        "SELECT deleted_at FROM questions_detail WHERE id = ?", (second_detail,)
    ).fetchone()["deleted_at"] is None
    assert test_db.execute(
        "SELECT deleted_at FROM interview WHERE id = ?", (second_id,)
    ).fetchone()["deleted_at"] is None


@pytest.mark.asyncio
async def test_source_cleanup_failure_does_not_roll_back_interview_delete(
    test_db, monkeypatch
):
    """遗留题库异常不能让删除按钮返回 500 或回滚主记录。"""
    url = "internal://cleanup-failure"
    interview_id = _insert_interview(test_db, url)
    detail_id = _insert_detail(test_db, interview_id, url, "题目")
    test_db.commit()

    def fail_cleanup(cursor, source_url):
        raise RuntimeError("模拟旧题库来源异常")

    monkeypatch.setattr(data, "_cleanup_sources_for_url", fail_cleanup)
    result = await _delete_interview(monkeypatch, interview_id)

    assert result == {"status": "success"}
    assert test_db.execute(
        "SELECT deleted_at FROM interview WHERE id = ?", (interview_id,)
    ).fetchone()["deleted_at"] is not None
    assert test_db.execute(
        "SELECT deleted_at FROM questions_detail WHERE id = ?", (detail_id,)
    ).fetchone()["deleted_at"] is not None

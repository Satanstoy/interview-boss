"""Regression tests for question-bank JSON/normalized-table integrity."""

from __future__ import annotations

import json

import pytest


def _insert_question(
    conn,
    question_id: int,
    question: str,
    *,
    status: str = "approved",
    owner_id=None,
    submitted_by=None,
    sources=None,
    original_questions=None,
    original_question_sources=None,
):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, status, owner_id, submitted_by, frequency, sources, "
        "original_questions, original_question_sources, cat1, cat2, job_position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'A', 'B', '后端开发')",
        (
            question_id,
            question,
            status,
            owner_id,
            submitted_by,
            len(original_questions or []),
            json.dumps(sources or [], ensure_ascii=False),
            json.dumps(original_questions or [], ensure_ascii=False),
            json.dumps(original_question_sources or [], ensure_ascii=False),
        ),
    )


def test_canonicalize_exact_normalized_variant_merges_sources():
    from app.services.question_bank_integrity import canonicalize_question_bank_payload

    sources, questions, question_sources = canonicalize_question_bank_payload(
        [
            {"url": "u1", "company": "A"},
            {"url": "u2", "company": "B"},
        ],
        ["对RAG的理解", "另一个问题"],
        [
            {"question": "对rag的理解", "sources": [{"url": "u2"}]},
            {"question": "另一个问题", "sources": [{"url": "u1"}]},
        ],
    )

    assert questions == ["对RAG的理解", "另一个问题"]
    assert [source["url"] for source in sources] == ["u1", "u2"]
    assert question_sources[0]["question"] == "对RAG的理解"
    assert {source["url"] for source in question_sources[0]["sources"]} == {"u2"}


def test_sync_projection_fails_closed_and_matches_json(test_db):
    from app.services.question_bank_integrity import sync_question_bank_projections

    _insert_question(test_db, 1, "代表题")
    sources = [{"url": "u1", "company": "A", "round": "一面"}]
    questions = ["原始题"]
    question_sources = [{"question": "原始题", "sources": sources}]
    test_db.execute(
        "UPDATE question_bank SET sources = ?, original_questions = ?, "
        "original_question_sources = ?, frequency = ? WHERE id = 1",
        (
            json.dumps(sources, ensure_ascii=False),
            json.dumps(questions, ensure_ascii=False),
            json.dumps(question_sources, ensure_ascii=False),
            len(questions),
        ),
    )

    sync_question_bank_projections(
        test_db.cursor(), 1, sources, questions, question_sources
    )

    assert test_db.execute(
        "SELECT COUNT(*) FROM question_sources WHERE question_bank_id = 1 "
        "AND deleted_at IS NULL"
    ).fetchone()[0] == 1
    assert test_db.execute(
        "SELECT COUNT(*) FROM question_original_items WHERE question_bank_id = 1 "
        "AND deleted_at IS NULL"
    ).fetchone()[0] == 1
    assert test_db.execute(
        "SELECT COUNT(*) FROM question_original_item_sources WHERE original_item_id = "
        "(SELECT id FROM question_original_items WHERE question_bank_id = 1) "
        "AND deleted_at IS NULL"
    ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_approval_merges_pending_duplicate_into_existing_public_question(
    test_db, monkeypatch
):
    import app.routers.admin_review as admin_review

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (1, 'submitter', 'x')"
    )
    _insert_question(
        test_db,
        10,
        "什么是RAG",
        sources=[{"url": "u1"}],
        original_questions=["什么是RAG"],
        original_question_sources=[
            {"question": "什么是RAG", "sources": [{"url": "u1"}]}
        ],
    )
    _insert_question(
        test_db,
        11,
        "什么是 RAG？",
        status="pending",
        submitted_by=1,
        sources=[{"url": "u2"}],
        original_questions=["什么是 RAG？"],
        original_question_sources=[
            {"question": "什么是 RAG？", "sources": [{"url": "u2"}]}
        ],
    )
    test_db.commit()

    async def run_sync(fn):
        return fn()

    monkeypatch.setattr(admin_review, "run_db", run_sync)
    await admin_review.approve_question(11, {"id": 99})

    target = test_db.execute(
        "SELECT sources, original_questions, original_question_sources FROM question_bank WHERE id = 10"
    ).fetchone()
    assert {item["url"] for item in json.loads(target["sources"])} == {"u1", "u2"}
    assert len(json.loads(target["original_questions"])) == 1
    assert {
        item["url"]
        for item in json.loads(target["original_question_sources"])[0]["sources"]
    } == {"u1", "u2"}
    assert test_db.execute(
        "SELECT deleted_at FROM question_bank WHERE id = 11"
    ).fetchone()[0] is not None
    assert test_db.execute(
        "SELECT COUNT(*) FROM question_bank WHERE owner_id IS NULL "
        "AND status = 'approved' AND deleted_at IS NULL"
    ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_manual_merge_does_not_append_normalized_duplicate(
    test_db, monkeypatch
):
    import app.routers.questions_pkg.mutations as mutations
    from app.models.schemas import MergeOriginalQuestionRequest

    _insert_question(
        test_db,
        20,
        "源聚类",
        sources=[{"url": "u1"}, {"url": "u3"}],
        original_questions=["什么是RAG", "保留题"],
        original_question_sources=[
            {"question": "什么是RAG", "sources": [{"url": "u1"}]},
            {"question": "保留题", "sources": [{"url": "u3"}]},
        ],
    )
    _insert_question(
        test_db,
        21,
        "目标聚类",
        sources=[{"url": "u2"}],
        original_questions=["什么是 RAG？"],
        original_question_sources=[
            {"question": "什么是 RAG？", "sources": [{"url": "u2"}]}
        ],
    )
    test_db.commit()

    async def run_sync(fn):
        return fn()

    async def no_cache_invalidation():
        return None

    async def unified(*args, **kwargs):
        return "统一题"

    monkeypatch.setattr(mutations, "run_db", run_sync)
    monkeypatch.setattr(mutations, "invalidate_master_bank_cache", no_cache_invalidation)
    monkeypatch.setattr(mutations, "generate_unified_question", unified)

    await mutations.merge_question(
        20,
        MergeOriginalQuestionRequest(original_question="什么是RAG", target_id=21),
        {"id": 99},
    )

    target = test_db.execute(
        "SELECT original_questions, original_question_sources, sources FROM question_bank WHERE id = 21"
    ).fetchone()
    assert len(json.loads(target["original_questions"])) == 1
    assert {item["url"] for item in json.loads(target["sources"])} == {"u1", "u2"}
    assert test_db.execute(
        "SELECT COUNT(*) FROM question_original_items WHERE question_bank_id = 21 "
        "AND deleted_at IS NULL"
    ).fetchone()[0] == 1


def test_compact_merge_keeps_json_and_normalized_sources_aligned(test_db):
    """审计 D9：compaction 合并后 question_bank JSON 双写列必须与规范化表一致。

    复现审计实测漂移（sources 含 xsec_token 笔记 URL 未落 question_sources 表）：

    - survivor 已有活跃的 question_sources 行（URL `u1`）。
    - 被合并单例的 JSON sources 复用 `u1` 并新增一个 xsec_token 笔记 URL `u2`。
    - 旧实现用 `delete_all_for_qb`（软删）+`insert_source`（INSERT OR IGNORE）重建规范化表：
      `u1` 行软删后因 `UNIQUE(question_bank_id, url)` 无法重新插入，导致 JSON 持有 `u1`
      而 question_sources 表中 `u1` 已软删 —— JSON/表不一致且静默通过（不报错）。
    - 修复后 compaction 合并统一走 sync_question_bank_projections（事务内重建 + 失败回滚），
      `u1` 被恢复（deleted_at=NULL）、`u2` 落表，JSON 与表严格一致。
    """
    from app.services.pipeline.compact import _do_merge_to_existing

    # survivor：JSON sources 与 question_sources 表初始一致（含活跃 u1 行）
    _insert_question(
        test_db,
        1,
        "什么是 RAG",
        sources=[{"url": "u1", "company": "A"}],
        original_questions=["什么是 RAG"],
        original_question_sources=[
            {"question": "什么是 RAG", "sources": [{"url": "u1", "company": "A"}]}
        ],
    )
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round) VALUES (1, 'u1', 'A', '')"
    )
    # 被合并单例 sources 复用 u1 并新增 xsec_token 笔记 URL u2
    _insert_question(
        test_db,
        2,
        "RAG 是什么",
        status="approved",
        sources=[{"url": "u1", "company": "A"}, {"url": "u2", "company": "B"}],
        original_questions=["RAG 是什么"],
        original_question_sources=[
            {"question": "RAG 是什么", "sources": [{"url": "u1"}, {"url": "u2"}]}
        ],
    )
    test_db.commit()

    _do_merge_to_existing(
        1,
        {
            "id": 2,
            "question": "RAG 是什么",
            "cat2": "B",
            "sources": json.dumps(
                [{"url": "u1", "company": "A"}, {"url": "u2", "company": "B"}],
                ensure_ascii=False,
            ),
            "original_questions": json.dumps(["RAG 是什么"], ensure_ascii=False),
            "original_question_sources": json.dumps(
                [
                    {
                        "question": "RAG 是什么",
                        "sources": [{"url": "u1"}, {"url": "u2"}],
                    }
                ],
                ensure_ascii=False,
            ),
        },
        operation_type="compaction",
        phase="test",
        cat2="B",
        confidence=0.9,
    )
    test_db.commit()

    # JSON sources 集合 = 活跃 question_sources 集合（u1 恢复 + u2 落表）
    row = test_db.execute(
        "SELECT sources FROM question_bank WHERE id = 1"
    ).fetchone()
    json_urls = {s["url"] for s in json.loads(row["sources"])}
    table_urls = {
        r[0]
        for r in test_db.execute(
            "SELECT url FROM question_sources WHERE question_bank_id = 1 AND deleted_at IS NULL"
        ).fetchall()
    }
    assert json_urls == {"u1", "u2"}
    assert table_urls == {"u1", "u2"}, (
        f"compaction 合并后 JSON/表漂移: json={sorted(json_urls)} table={sorted(table_urls)}"
    )


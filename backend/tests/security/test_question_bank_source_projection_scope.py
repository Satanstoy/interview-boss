"""Soft-deleted normalized sources must stay out of API projections."""

from __future__ import annotations

from app.db.question_bank_sources import build_api_shapes_batch_filtered


def test_batch_source_projection_excludes_all_soft_deleted_rows(test_db):
    test_db.execute(
        "INSERT INTO question_bank (id, question, owner_id, status) "
        "VALUES (901, '聚合题', NULL, 'approved')"
    )
    test_db.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round) "
        "VALUES (901, 'https://active.example', '活跃公司', '一面')"
    )
    test_db.execute(
        "INSERT INTO question_sources "
        "(question_bank_id, url, company, round, deleted_at) "
        "VALUES (901, 'https://deleted.example', '删除公司', '二面', CURRENT_TIMESTAMP)"
    )
    active_item = test_db.execute(
        "INSERT INTO question_original_items (question_bank_id, question_text) "
        "VALUES (901, '活跃原题')"
    ).lastrowid
    deleted_item = test_db.execute(
        "INSERT INTO question_original_items "
        "(question_bank_id, question_text, deleted_at) "
        "VALUES (901, '删除原题', CURRENT_TIMESTAMP)"
    ).lastrowid
    test_db.execute(
        "INSERT INTO question_original_item_sources "
        "(original_item_id, url, company, round) "
        "VALUES (?, 'https://active.example', '活跃公司', '一面')",
        (active_item,),
    )
    test_db.execute(
        "INSERT INTO question_original_item_sources "
        "(original_item_id, url, company, round, deleted_at) "
        "VALUES (?, 'https://deleted.example', '删除公司', '二面', CURRENT_TIMESTAMP)",
        (active_item,),
    )
    test_db.execute(
        "INSERT INTO question_original_item_sources "
        "(original_item_id, url, company, round) "
        "VALUES (?, 'https://deleted-item.example', '删除原题公司', '三面')",
        (deleted_item,),
    )
    test_db.commit()

    shape = build_api_shapes_batch_filtered(test_db, [901], "public", 7)[901]

    assert shape["sources"] == [
        {"url": "https://active.example", "company": "活跃公司", "round": "一面"}
    ]
    assert shape["original_questions"] == ["活跃原题"]
    assert shape["original_question_sources"] == [
        {
            "question": "活跃原题",
            "sources": [
                {
                    "url": "https://active.example",
                    "company": "活跃公司",
                    "round": "一面",
                }
            ],
        }
    ]

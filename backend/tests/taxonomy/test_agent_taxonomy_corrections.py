"""Regression tests for the Agent-only taxonomy correction migration."""

from __future__ import annotations


def test_agent_manual_correction_migration_only_updates_agent_rows(test_db):
    from app import db
    from app.core.taxonomy import TAXONOMY_VERSION

    migration = getattr(
        db.migrations,
        "_migration_107_agent_taxonomy_corrections",
        None,
    )
    assert callable(migration)

    test_db.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, ai_answer, status, owner_id, job_position) "
        "VALUES (?, ?, ?, ?, NULL, 'approved', NULL, ?)",
        (
            5889,
            "滑动窗口最大值",
            "G.算法与数据结构",
            "G1.数据结构",
            "agent开发/大模型应用开发/大模型开发",
        ),
    )
    test_db.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, ai_answer, status, owner_id, job_position) "
        "VALUES (?, ?, ?, ?, NULL, 'approved', NULL, ?)",
        (
            58890,
            "滑动窗口最大值",
            "G.算法与数据结构",
            "G1.数据结构",
            "后端开发",
        ),
    )
    test_db.commit()

    migration(test_db)
    test_db.commit()

    agent_row = test_db.execute(
        "SELECT cat1, cat2, taxonomy_version FROM question_bank WHERE id = 5889"
    ).fetchone()
    assert (agent_row["cat1"], agent_row["cat2"], agent_row["taxonomy_version"]) == (
        "G.算法与数据结构",
        "G2.算法手撕",
        TAXONOMY_VERSION,
    )

    backend_row = test_db.execute(
        "SELECT cat1, cat2 FROM question_bank WHERE id = 58890"
    ).fetchone()
    assert (backend_row["cat1"], backend_row["cat2"]) == (
        "G.算法与数据结构",
        "G1.数据结构",
    )

    audit = test_db.execute(
        "SELECT old_cat1, old_cat2, new_cat1, new_cat2, reason "
        "FROM taxonomy_migration_audit "
        "WHERE migration_version = '1.1-agent-manual' AND record_id = 5889"
    ).fetchone()
    assert tuple(audit) == (
        "G.算法与数据结构",
        "G1.数据结构",
        "G.算法与数据结构",
        "G2.算法手撕",
        "manual_agent_review",
    )


def test_missing_answer_selector_is_agent_only_and_excludes_deleted_rows(test_db):
    from app.db import taxonomy_verification

    selector = getattr(
        taxonomy_verification,
        "select_agent_question_ids_without_answers",
        None,
    )
    assert callable(selector)

    test_db.executemany(
        "INSERT INTO question_bank "
        "(id, question, ai_answer, status, owner_id, job_position, deleted_at) "
        "VALUES (?, ?, ?, 'approved', NULL, ?, ?)",
        [
            (7001, "Agent 架构设计", None, "agent开发/大模型应用开发/大模型开发", None),
            (7002, "后端题", None, "后端开发", None),
            (7003, "Agent 评测", "[生成失败，请手动重试]", "agent开发/大模型应用开发/大模型开发", None),
            (7004, "已删除 Agent 题", None, "agent开发/大模型应用开发/大模型开发", "2026-08-01"),
        ],
    )
    test_db.commit()

    assert selector(test_db) == [7001, 7003]


def test_missing_answer_selector_can_match_api_visibility(test_db):
    from app.db.taxonomy_verification import select_agent_question_ids_without_answers

    test_db.executemany(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
        [(7007, "owner7007", "hash"), (7042, "owner7042", "hash")],
    )
    test_db.executemany(
        "INSERT INTO question_bank "
        "(id, question, ai_answer, status, owner_id, job_position, deleted_at) "
        "VALUES (?, ?, NULL, 'approved', ?, ?, NULL)",
        [
            (7010, "公共 Agent 题", None, "agent开发/大模型应用开发/大模型开发"),
            (7011, "我的 Agent 题", 7007, "agent开发/大模型应用开发/大模型开发"),
            (7012, "别人的 Agent 题", 7042, "agent开发/大模型应用开发/大模型开发"),
        ],
    )
    test_db.commit()

    assert select_agent_question_ids_without_answers(test_db, owner_id=7007) == [
        7010,
        7011,
    ]

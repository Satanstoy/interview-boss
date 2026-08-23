"""Regression tests for the taxonomy 1.1 rollout.

These tests intentionally exercise the same migration function that production
startup/deploy uses; they never open the configured production database.
"""

from __future__ import annotations

import json


def test_taxonomy_v11_exposes_language_and_agent_categories():
    from app.core.taxonomy import (
        AGENT_TAXONOMY,
        BACKEND_TAXONOMY,
        TAXONOMY_VERSION,
    )

    assert TAXONOMY_VERSION == "1.1"
    agent_children = {
        child
        for category in AGENT_TAXONOMY["categories"]
        for child in category["children"]
    }
    backend_children = {
        child
        for category in BACKEND_TAXONOMY["categories"]
        for child in category["children"]
    }

    assert any("Python" in child for child in agent_children)
    assert any("Java" in child for child in agent_children)
    assert any("Python" in child for child in backend_children)
    assert any("Java" in child for child in backend_children)
    assert any("MCP" in child or "工具" in child for child in agent_children)


def test_legacy_category_mapping_is_deterministic_by_role_and_question():
    from app.core.taxonomy import map_legacy_category

    assert map_legacy_category(
        "B.Agent与LLM应用",
        "B2.RAG系统设计",
        "请介绍 RAG 多路召回如何优化",
        "Agent开发",
    )[:2] == ("D.RAG与知识工程", "D1.RAG检索增强")
    assert map_legacy_category(
        "C.基础工程能力",
        "C1.编程语言基础",
        "Java 中 HashMap 的实现原理是什么？",
        "后端开发",
    )[:2] == ("B.Java/Python语言与运行时", "B1.Java语言基础与集合")
    assert map_legacy_category(
        "C.基础工程能力",
        "C1.编程语言基础",
        "Python asyncio 和协程如何调度？",
        "后端开发",
    )[:2] == ("B.Java/Python语言与运行时", "B5.Python异步与并发")
    assert map_legacy_category(
        "旧分类",
        "旧子类",
        "无法判断的题目",
        "后端开发",
    )[:2] == ("Z.其他", "Z1.待复核")


def test_migration_102_rewrites_rows_preserves_answers_and_seeds_all_positions(test_db):
    from app.db.migrations import _migration_102_taxonomy_v11
    from app.core.taxonomy import TAXONOMY_VERSION

    test_db.execute(
        "INSERT OR IGNORE INTO job_positions (id, name, description) VALUES (901, ?, '')",
        ("后端开发",),
    )
    test_db.execute(
        "INSERT OR IGNORE INTO job_positions (id, name, description) VALUES (902, ?, '')",
        ("Agent开发",),
    )
    test_db.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, ai_answer, status, owner_id, job_position) "
        "VALUES (901, ?, ?, ?, ?, 'approved', NULL, ?)",
        (
            "Java HashMap 原理",
            "C.基础工程能力",
            "C1.编程语言基础",
            "旧答案必须保留",
            "后端开发",
        ),
    )
    test_db.execute(
        "INSERT INTO questions_detail "
        "(id, question, cat1, cat2, job_position) VALUES (902, ?, ?, ?, ?)",
        (
            "Python asyncio 协程",
            "C.基础工程能力",
            "C1.编程语言基础",
            "Agent开发",
        ),
    )
    test_db.commit()

    _migration_102_taxonomy_v11(test_db)
    test_db.commit()

    qb = test_db.execute(
        "SELECT cat1, cat2, ai_answer, taxonomy_version, answer_taxonomy_version "
        "FROM question_bank WHERE id = 901"
    ).fetchone()
    assert (qb["cat1"], qb["cat2"]) == (
        "B.Java/Python语言与运行时",
        "B1.Java语言基础与集合",
    )
    assert qb["ai_answer"] == "旧答案必须保留"
    assert qb["taxonomy_version"] == TAXONOMY_VERSION
    assert qb["answer_taxonomy_version"] is None

    qd = test_db.execute(
        "SELECT cat1, cat2, taxonomy_version FROM questions_detail WHERE id = 902"
    ).fetchone()
    assert (qd["cat1"], qd["cat2"], qd["taxonomy_version"]) == (
        "E.语言与基础工程",
        "E2.Python异步与并发",
        TAXONOMY_VERSION,
    )

    system_taxonomies = {
        row["position_name"]: json.loads(row["categories_json"])
        for row in test_db.execute(
            "SELECT position_name, categories_json FROM taxonomy "
            "WHERE source = 'system' AND owner_id IS NULL"
        ).fetchall()
    }
    assert "后端开发" in system_taxonomies
    assert "Agent开发" in system_taxonomies
    assert any(
        "Java" in child
        for category in system_taxonomies["后端开发"]
        for child in category["children"]
    )
    assert test_db.execute(
        "SELECT COUNT(*) FROM taxonomy_migration_audit WHERE migration_version = '1.1'"
    ).fetchone()[0] >= 2


def test_question_tagging_eval_uses_taxonomy_v11_suite():
    from app.evaluation.benchmark_catalog import load_suite_definition

    suite = load_suite_definition("question-tagging-eval@1.1")

    assert suite["version"] == "1.1"
    assert suite["target_type"] == "question_tagging"
    assert any(
        "Java" in str(case["input_snapshot"]["taxonomy"])
        or "Python" in str(case["input_snapshot"]["taxonomy"])
        for case in suite["cases"]
    )


def test_taxonomy_v11_verifier_reports_migration_and_refresh_counts(test_db):
    from app.db.taxonomy_verification import inspect_taxonomy_v11

    report = inspect_taxonomy_v11(test_db)

    assert report["taxonomy_version"] == "1.1"
    assert report["schema_version"] >= 102
    assert report["system_taxonomy_count"] >= 1
    assert "answer_refresh_required" in report

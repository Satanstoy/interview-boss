import json

from app.db.migrations import _migration_063_answer_sources


def test_migration_creates_answer_sources_column(test_db):
    """question_bank 应有 answer_sources 列（联网搜索来源 JSON）"""
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    assert "answer_sources" in columns


def test_migration_is_idempotent(test_db):
    """重复执行 063 迁移不抛异常，列保持存在"""
    _migration_063_answer_sources(test_db)
    test_db.commit()
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    assert "answer_sources" in columns

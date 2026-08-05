import json


def test_migration_creates_answer_sources_column(test_db):
    """question_bank 应有 answer_sources 列（联网搜索来源 JSON）"""
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    assert "answer_sources" in columns

"""Add missing Python labels without replacing configured taxonomy data."""

import json


def _migration_128_python_tags(conn):
    rows = conn.execute(
        "SELECT id, tags_json FROM taxonomy WHERE source = 'system' "
        "AND owner_id IS NULL AND position_name = ?",
        ("agent开发/大模型应用开发/大模型开发",),
    ).fetchall()
    for row in rows:
        tags = json.loads(row[1] or "[]")
        for tag in ("Python基础", "数据类型", "对象身份与相等性"):
            if tag not in tags:
                tags.append(tag)
        conn.execute(
            "UPDATE taxonomy SET tags_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(tags, ensure_ascii=False), row[0]),
        )


def _migration_129_answer_review(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(question_bank)")}
    if "answer_review_status" not in columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN answer_review_status TEXT")
    if "answer_review_issues" not in columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN answer_review_issues TEXT")
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS invalidate_question_answer_review
        AFTER UPDATE OF ai_answer, question ON question_bank
        WHEN NEW.ai_answer IS NOT OLD.ai_answer OR NEW.question IS NOT OLD.question
        BEGIN
            UPDATE question_bank SET answer_review_status = NULL,
                answer_review_issues = NULL WHERE id = NEW.id;
        END
    """)

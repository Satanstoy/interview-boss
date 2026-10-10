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

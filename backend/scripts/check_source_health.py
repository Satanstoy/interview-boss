#!/usr/bin/env python3
"""
面经/题目来源健康检查脚本：检测来源数据是否出现新的不一致。

检查项：
1. 同 url_signature 重复面经（interview / jd，xsec_token 等变体重复上传）
2. internal:// 无效来源数量（interview / jd / question_sources）
3. 同 qb 内同笔记多 URL 变体（小红书/牛客/Boss 签名相同但完整 URL 不同）
4. question_bank.sources JSON 与 question_sources 表双写不一致
5. 孤儿 questions_detail（interview_id 指向不存在的面经）

用法：
  docker compose exec backend uv run python backend/scripts/check_source_health.py

退出码：0 = 健康；1 = 发现问题。
"""
import json
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "interview-boss.db",
)

_NOTE_RE = re.compile(r"xiaohongshu\.com/(?:explore|item|discovery/item)/([0-9a-f]+)")
_PROBLEMS = []


def _note_key(url):
    m = _NOTE_RE.search(url or "")
    return m.group(1) if m else url


def _problem(desc):
    _PROBLEMS.append(desc)
    print(f"  ❌ {desc}")


def check(conn):
    print("🔍 面经/来源健康检查")
    print("=" * 60)

    # 1. 同签名重复面经
    print("\n1. 同签名重复面经")
    dup_found = False
    for table in ("interview", "jd"):
        rows = conn.execute(
            f"""
            SELECT url_signature, COUNT(*) c FROM {table}
            WHERE deleted_at IS NULL AND url_signature != ''
            GROUP BY url_signature HAVING c > 1
            """
        ).fetchall()
        for sig, c in rows:
            _problem(f"{table} 表同签名 {sig} 有 {c} 条活跃记录")
            dup_found = True
    if not dup_found:
        print("  ✅ 无重复")

    # 2. internal:// 无效来源（提示级：历史遗留的无链接面经，展示层已降级，需关注增长）
    print("\n2. internal:// 来源（提示，不阻断）")
    for table in ("interview", "jd"):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
        ).fetchone()[0]
        print(f"  ℹ️ {table} 表 {n} 条")
    n = conn.execute(
        "SELECT COUNT(*) FROM question_sources WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
    ).fetchone()[0]
    print(f"  ℹ️ question_sources {n} 行")

    # 3. 同 qb 内同笔记多 URL 变体
    print("\n3. 同 qb 内同笔记多 URL 变体")
    rows = conn.execute(
        "SELECT question_bank_id, url FROM question_sources WHERE deleted_at IS NULL"
    ).fetchall()
    by_qb = {}
    for qb_id, u in rows:
        by_qb.setdefault(qb_id, {}).setdefault(_note_key(u), set()).add(u)
    bad = [
        (qb, nk, len(urls))
        for qb, notes in by_qb.items()
        for nk, urls in notes.items()
        if len(urls) > 1 and nk.startswith(("69", "5", "62"))
    ]
    # 只对含域名路径的笔记 id 报告（generic 变体噪音大）
    bad = [
        (qb, nk, len(urls))
        for qb, notes in by_qb.items()
        for nk, urls in notes.items()
        if len(urls) > 1
        and any("xiaohongshu.com" in u for u in urls)
        or any("nowcoder.com" in u for u in urls)
        or any("zhipin.com" in u for u in urls)
    ]
    if bad:
        for qb, nk, c in bad[:10]:
            _problem(f"qb={qb} 笔记 {nk} 有 {c} 个 URL 变体")
    else:
        print("  ✅ 无变体")

    # 4. sources JSON 与 question_sources 表双写一致性
    print("\n4. JSON 双写一致性（sources vs question_sources 表）")
    mismatched = 0
    total = 0
    for r in conn.execute(
        "SELECT id, sources FROM question_bank WHERE deleted_at IS NULL AND sources IS NOT NULL AND sources != '[]'"
    ).fetchall():
        total += 1
        try:
            json_urls = {s.get("url") for s in json.loads(r[1])}
        except Exception:
            _problem(f"qb={r[0]} sources JSON 解析失败")
            mismatched += 1
            continue
        table_urls = {
            row[0]
            for row in conn.execute(
                "SELECT url FROM question_sources WHERE question_bank_id = ? AND deleted_at IS NULL",
                (r[0],),
            )
        }
        if json_urls != table_urls:
            mismatched += 1
            if mismatched <= 3:
                _problem(f"qb={r[0]} JSON {len(json_urls)} 条 vs 表 {len(table_urls)} 条，差集: {json_urls ^ table_urls}")
    if not mismatched:
        print(f"  ✅ {total} 个 qb 全部一致")

    # 5. 孤儿 questions_detail（提示级：历史遗留，需单独决策）
    print("\n5. 孤儿 questions_detail（提示，不阻断）")
    n = conn.execute(
        "SELECT COUNT(*) FROM questions_detail qd LEFT JOIN interview i ON i.id = qd.interview_id WHERE i.id IS NULL"
    ).fetchone()[0]
    print(f"  ℹ️ {n} 条 detail 的 interview 不存在")

    print("=" * 60)
    return len(_PROBLEMS)


def main():
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        sys.exit(2)
    conn = sqlite3.connect(DB_PATH)
    try:
        n = check(conn)
    finally:
        conn.close()
    if n:
        print(f"\n发现 {n} 类问题，需要人工处理。")
        sys.exit(1)
    print("\n✅ 全部健康")


if __name__ == "__main__":
    main()

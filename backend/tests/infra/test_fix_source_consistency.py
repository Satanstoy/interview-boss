"""fix_source_consistency.py 数据修复脚本逻辑测试。

覆盖：url_signature 回填、同签名重复面经合并（detail 重挂去重、
来源表 URL 归一、JSON 双写同步、软删被合并记录）。
"""

import importlib.util
import json
import os
import sqlite3

import pytest

_script_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
    "fix_source_consistency.py",
)
_spec = importlib.util.spec_from_file_location("fix_source_consistency", _script_path)
fixer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixer)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE interview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, company TEXT, round TEXT, focus TEXT,
            questions_list TEXT, difficulty TEXT, season TEXT,
            owner_id INTEGER, status TEXT, url_signature TEXT DEFAULT '',
            job_position TEXT DEFAULT '', deleted_at TIMESTAMP
        )"""
    )
    c.execute(
        """CREATE TABLE jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT,
            owner_id INTEGER, url_signature TEXT DEFAULT '', deleted_at TIMESTAMP
        )"""
    )
    c.execute(
        """CREATE TABLE questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER, question TEXT, cat1 TEXT, url TEXT,
            owner_id INTEGER, deleted_at TIMESTAMP
        )"""
    )
    c.execute(
        """CREATE TABLE question_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER, url TEXT, company TEXT DEFAULT '',
            round TEXT DEFAULT '', deleted_at TIMESTAMP,
            UNIQUE(question_bank_id, url)
        )"""
    )
    c.execute(
        """CREATE TABLE question_original_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER, question_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMP,
            UNIQUE(question_bank_id, question_text)
        )"""
    )
    c.execute(
        """CREATE TABLE question_original_item_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_item_id INTEGER, url TEXT, company TEXT DEFAULT '',
            round TEXT DEFAULT '', deleted_at TIMESTAMP
        )"""
    )
    c.execute(
        """CREATE TABLE question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT DEFAULT '', owner_id INTEGER,
            sources TEXT, original_question_sources TEXT,
            status TEXT DEFAULT 'approved', deleted_at TIMESTAMP
        )"""
    )
    yield c
    c.close()


def _insert(conn, table, **kwargs):
    cols = ", ".join(kwargs)
    marks = ", ".join(["?"] * len(kwargs))
    cur = conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(kwargs.values())
    )
    return cur.lastrowid


def test_backfill_url_signatures(conn):
    """空签名记录回填；internal:// 无签名；已有签名不动"""
    _insert(conn, "interview", url="https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=ABnKvS1dmNyhjo86JVSTRWDa9kCagyzHcr_C6-9rTrydU=", url_signature="")
    _insert(conn, "interview", url="internal://5ildmcA5aKMt3W5UeGHkzQ", url_signature="")
    _insert(conn, "jd", url="https://www.xiaohongshu.com/explore/69e9d944000000001b0213b2?xsec_token=ABZNTazy289-2Z16bmk6sG9KZO4klivnIaRQmBU0Sew0c=", url_signature="")

    n = fixer.backfill_url_signatures(conn, dry_run=False)
    assert n == 3  # 两条 xhs + internal:// 也获得 generic 签名（与 _extract_url_signature 一致）
    rows = conn.execute("SELECT url_signature FROM interview").fetchall()
    sigs = [r[0] for r in rows]
    assert "xhs:69ebf7ec000000001f0075ba" in sigs
    assert "generic:5ildmcA5aKMt3W5UeGHkzQ" in sigs  # internal:// 归入 generic
    jd_sig = conn.execute("SELECT url_signature FROM jd").fetchone()[0]
    assert jd_sig == "xhs:69e9d944000000001b0213b2"


def test_merge_duplicate_interviews(conn):
    """同签名两条面经：detail 重挂去重、来源表归一、JSON 同步、软删被合并方"""
    keep_url = "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=ABnKvS1dmNyhjo86JVSTRWDa9kCagyzHcr_C6-9rTrydU=&xsec_source=pc_user&source=web_user_page"
    drop_url = "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=ABnKvS1dmNyhjo86JVSTRWDaD2DRas043dJnwM-09uRKg=&xsec_source=pc_collect"
    sig = "xhs:69ebf7ec000000001f0075ba"

    keep_id = _insert(conn, "interview", url=keep_url, url_signature=sig)
    drop_id = _insert(conn, "interview", url=drop_url, url_signature=sig)

    # detail：keep 有 Q1，drop 有 Q1(重复) + Q2
    _insert(conn, "questions_detail", interview_id=keep_id, question="Q1")
    _insert(conn, "questions_detail", interview_id=drop_id, question="Q1")
    _insert(conn, "questions_detail", interview_id=drop_id, question="Q2")

    # question_sources：同一 qb 下 keep_url 和 drop_url 各一行
    qb_id = _insert(conn, "question_bank", sources="", original_question_sources="")
    _insert(conn, "question_sources", question_bank_id=qb_id, url=keep_url)
    _insert(conn, "question_sources", question_bank_id=qb_id, url=drop_url)

    # original_item_sources：drop_url 一行（关联公共 qb 的 original_item）
    oi_id = _insert(conn, "question_original_items", question_bank_id=qb_id, question_text="Q1")
    _insert(conn, "question_original_item_sources", original_item_id=oi_id, url=drop_url)

    # JSON 双写列：含 drop_url
    conn.execute(
        "UPDATE question_bank SET sources = ?, original_question_sources = ? WHERE id = ?",
        (
            json.dumps([{"url": drop_url}, {"url": keep_url}], ensure_ascii=False),
            json.dumps([{"question": "Q1", "sources": [{"url": drop_url}]}], ensure_ascii=False),
            qb_id,
        ),
    )
    conn.commit()

    merged = fixer.merge_duplicate_interviews(conn, dry_run=False)

    assert merged == 1
    # 被合并方软删
    assert conn.execute("SELECT deleted_at FROM interview WHERE id = ?", (drop_id,)).fetchone()[0] is not None
    assert conn.execute("SELECT deleted_at FROM interview WHERE id = ?", (keep_id,)).fetchone()[0] is None
    # detail 全部重挂 keep 且 Q1 去重 → 2 条（Q1, Q2）
    details = conn.execute(
        "SELECT DISTINCT question FROM questions_detail WHERE interview_id = ?", (keep_id,)
    ).fetchall()
    assert sorted(r[0] for r in details) == ["Q1", "Q2"]
    assert conn.execute("SELECT COUNT(*) FROM questions_detail WHERE interview_id = ?", (drop_id,)).fetchone()[0] == 0
    # question_sources：全部归一为 keep_url 且只有 1 行活跃
    srcs = conn.execute(
        "SELECT url, deleted_at FROM question_sources WHERE question_bank_id = ?", (qb_id,)
    ).fetchall()
    assert sum(1 for s in srcs if s[1] is None) == 1
    assert all(s[0] == keep_url for s in srcs)
    # original_item_sources 归一
    ois = conn.execute("SELECT url FROM question_original_item_sources").fetchall()
    assert all(r[0] == keep_url for r in ois)
    # JSON 双写列归一
    qb = conn.execute("SELECT sources, original_question_sources FROM question_bank WHERE id = ?", (qb_id,)).fetchone()
    assert json.loads(qb[0]) == [{"url": keep_url}]
    assert json.loads(qb[1])[0]["sources"][0]["url"] == keep_url


def test_dry_run_does_not_modify(conn):
    keep_url = "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=A"
    drop_url = "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba?xsec_token=B"
    sig = "xhs:69ebf7ec000000001f0075ba"
    _insert(conn, "interview", url=keep_url, url_signature=sig)
    _insert(conn, "interview", url=drop_url, url_signature=sig)
    conn.commit()  # 固化基线，rollback 只撤销 dry-run 的写入

    n = fixer.backfill_url_signatures(conn, dry_run=True)
    merged = fixer.merge_duplicate_interviews(conn, dry_run=True)
    conn.rollback()  # dry-run 语义：写入但回滚

    assert n == 0  # 签名已有
    assert merged == 1  # 预览报出
    assert conn.execute("SELECT COUNT(*) FROM interview WHERE deleted_at IS NULL").fetchone()[0] == 2  # 回滚后未动
